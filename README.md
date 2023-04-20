# az
A simple amazon scraper

## Requirements
* python \>=3.9

## Installation
Install the required packages
```console
pip install -r requirements.txt
```
Update `config.yml`, make sure all the values entered are correct and valid
```yaml
webhook_url: 'https://discord.com/api/webhooks/...' # discord webhook url
cron_expr: '0 _ * * *' # cron expression, example: '0 10 * * *'  runs at 10am every day, learn more at crontab.guru
# 1: Only Changes , 2: Update Everything
log_level: 1
initial_update: true # update all products initially when the script is run
products:
  - # product url 1
  - # product url 2
cron_interval: 30 # check cron task every 30s
```

## Usage
Now just run the scraper using
```console
python scrape.py
```
override `initial_update` using the `-o` flag
```console
python scrape.py -o
```
