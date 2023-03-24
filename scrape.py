import os
import re
import sys
import time
import random
import traceback
from io import BytesIO
from datetime import datetime

import yaml
import requests
import pickledb
from bs4 import BeautifulSoup
from colorthief import ColorThief
from discord_webhook import DiscordWebhook, DiscordEmbed
from cron_validator import CronValidator, CronScheduler

headers = {
    'authority': 'www.amazon.in',
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-GB,en;q=0.9',
    'dnt': '1',
    'sec-ch-ua': '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36',
}
session = requests.Session()


# TODO: graph

def fix_d(s):  # cross platform datetime strftime
    return s.replace("%-", '%#') if os.name == 'nt' else s


def dominant_color(url):
    return '%02x%02x%02x' % ColorThief(BytesIO(requests.get(url).content)).get_color(quality = 10)


class Product:
    def __init__(self, url: str, db: pickledb.PickleDB, log_level: int, webhook_url):
        self.url = url
        self.db = db
        self.log_level = log_level
        self.thumbnail = ''
        self.webhook_url = webhook_url

    def fetch(self):
        soup = BeautifulSoup(session.get(self.url, headers = headers).content, "lxml")
        title, price, availability = map(lambda x: (elem := soup.select_one(x)) and elem.text.strip(),
                                         ('#productTitle', '#corePrice_feature_div span.a-offscreen', '#availability > span'))  # '.a-price-whole'
        self.thumbnail = self.thumbnail or (match := re.search(r'{\s*"landingImageUrl"\s*:\s*"(.+)"\s*}', str(soup))) and match.group(1)
        if not title:
            raise Exception(f"Invalid Product {self.url!r}")
        return title, (price or 'Unavailable'), availability  # float(re.sub(r'[^\d.]', '', price))

    @staticmethod
    def format_availability(availability):
        if "left in stock" in availability.lower():
            return f"```arm\n{availability.replace(' ', '_')}```"
        elif "in stock" in availability.lower():
            return f"```diff\n+{availability}```"
        elif "unavailable" in availability.lower():
            return f"```diff\n-{availability.rstrip('.')}```"

    def send_wh_message(self, prod, content, everyone = False):
        latest = prod['price_history'][-1]
        wh = DiscordWebhook(url = self.webhook_url)
        wh.set_content("@everyone" if everyone else '')
        embed = DiscordEmbed()
        embed.set_title(prod["title"])
        embed.set_url(self.url)
        embed.set_thumbnail(url = self.thumbnail)
        embed.set_description(content + f' - <t:{int(latest[2])}:R> \n {self.format_availability(latest[1])}')
        embed.set_color(prod['color'])
        embed.set_timestamp(int(latest[2]))
        wh.add_embed(embed)
        wh.execute()

    def notify(self, prod):
        history = prod["price_history"]
        latest = prod['price_history'][-1]
        change = False
        if len(history) == 1:
            return self.send_wh_message(prod, f"(Configured) `{latest[0]}`")
        if latest[0] != (old := history[-2][0]):
            self.send_wh_message(prod, f"Price Change! `{old}` => `{latest[0]}`", everyone = True)
            change = True
        if latest[1] != (old := history[-2][1]):
            self.send_wh_message(prod, f"(`{latest[0]}`) Availability Change! `{old}` => `{latest[1]}`", everyone = True)
            change = True
        if self.log_level == 2 and not change:
            self.send_wh_message(prod, f"General Update... `{latest[0]}`")

    def configure(self, title, price, availability):
        return {
            "title": title,
            "price_history": [(price, availability, int(time.time()))],
            "color": dominant_color(self.thumbnail) if self.thumbnail else f"{random.randint(0, 0xFFFFFF):06X}"
        }

    def update(self):
        try:
            prod = self.db.get(self.url)
            if not prod:
                prod = self.configure(*self.fetch())
            else:
                title, price, availability = self.fetch()
                prod["title"] = title
                prod["price_history"].append((price, availability, int(time.time())))
            self.notify(prod)
            self.db.set(self.url, prod)
            self.db.dump()
            print(f"{prod['title']} => {prod['price_history'][-1][0]} :: {prod['price_history'][-1][1]} @ {datetime.now():{fix_d('%-I:%M:%S %p, %b %d')}}")
        except Exception as err:
            formated_error = traceback.format_exception(type(err), err, err.__traceback__)
            wh = DiscordWebhook(url = self.webhook_url)
            wh.add_embed(DiscordEmbed(title = "An Exception Occured :(", description = '\n'.join(formated_error), url = self.url, color = "CC5500"))
            wh.execute()
            # print(*formated_error)
            traceback.print_exception(type(err), err, err.__traceback__)


class Amazon:
    def __init__(self, cron_expr, cron_interval, webhook_url, log_level, db_fp = "./products.db"):
        self.products = []
        self.db = pickledb.load(db_fp, True, True)
        self.webhook_url = webhook_url
        assert log_level in (1, 2)
        self.log_level = log_level
        assert CronValidator.parse(cron_expr)
        self.scheduler = CronScheduler(cron_expr)
        self.cron_interval = cron_interval

    def register(self, url):
        product = Product(url = url.split('?')[0], db = self.db, log_level = self.log_level, webhook_url = self.webhook_url)
        self.products.append(product)

    def register_many(self, urls):
        for url in urls:
            url and self.register(url)

    def update_all(self):
        for product in self.products:
            product.update()

    def run_forever(self):
        print("Next Execution Scheduled at", self.scheduler.next_execution_time.strftime(fix_d(f"%-I:%M:%S %p, %a %-d %b")))
        while True:
            if self.scheduler.time_for_execution():
                self.update_all()
                print("Next Execution Scheduled at", self.scheduler.next_execution_time.strftime(fix_d(f"%-I:%M:%S %p, %a %-d %b")))
            time.sleep(self.cron_interval)


def main():
    with open("config.yml", "r") as f:
        config = yaml.safe_load(f)
    try:
        scraper = Amazon(**{k: v for k, v in config.items() if k in ["cron_expr", "cron_interval", "webhook_url", "log_level"]})
    except AssertionError:
        raise Exception("Your Config file might be incorrect.")

    scraper.register_many(config['products'])

    if '-o' in sys.argv:  # override intial update
        config['initial_update'] = not config['initial_update']

    config['initial_update'] and scraper.update_all()

    scraper.run_forever()


if __name__ == '__main__':
    main()
