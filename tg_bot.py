import sys, math, time, requests, pickle
from datetime import datetime
import collections
from repository.market import MarketRepository
import config

class TgBot(object):
    DB_FILENAME = 'db.pickle'
    CACHE_DURATION = 10  # seconds
    DEFAULT_FIAT = "USD"

    db = {} #this makes db static!

    def __init__(self):
        self.Repository = MarketRepository()

    def log(self, str):
        print('{} - {}'.format(datetime.today(), str))

    def getTgUrl(self, methodName):
        return 'https://api.telegram.org/bot{}/{}'.format(config.TG_TOKEN, methodName)

    def format_price(self, price):
        precision = max(1,min(-math.floor(math.log10(price))+2,8))       
        return f'{price:.{precision}f}'

    def get_price(self, fsym, tsym):
        if not self.Repository.isPricePairValid(fsym, tsym):
            print(f"price pair not valid {fsym} {tsym}")
        else:
            return self.Repository.get_price(fsym, tsym)

    def getTop(self):
        return self.Repository.get_top_coins()

    def get_symbols(self):
        return self.Repository.get_symbols()

    def sendMessage(self, msg, chatid, parse_mode=None):
        url = self.getTgUrl('sendMessage')
        r = requests.post(url=url, data={
            'chat_id': chatid,
            'text': msg,
            'parse_mode': parse_mode
        })
        return r

    def handleBotCommand(self, message):
        text = message['text']
        chatId = message['chat']['id']
        command = text.partition('/')[2]
        self.log('handling command "{}"...'.format(command))

        if command == 'start' or command == 'help':
            resp = "Hi, welcome to the Crypto price notification bot\nSet alerts on your favorite crypto currencies. Get notified and earn $$$"
            self.sendMessage(resp, chatId)

        elif command == 'all' or command == 'top':
            resp = self.getTop()
            self.sendMessage(resp, chatId, 'Markdown')

        elif command == 'alerts':
            if 'alerts' in self.db and chatId in self.db['alerts']:
                alerts=self.db['alerts'][chatId]
                msg='Current alerts:\n'
                for fsym in alerts:
                    for op in alerts[fsym]:
                        for tsym in alerts[fsym][op]:
                            for target in alerts[fsym][op][tsym]:
                                msg='{}{} {} {} {}\n'.format(msg, self.get_symbols()[fsym], op, target,tsym)
                self.sendMessage(msg, chatId)
            else:
                self.sendMessage('No alert is set',chatId)

        elif command=='clear':
            if 'alerts' in self.db and chatId in self.db['alerts']:
                self.db['alerts'].pop(chatId)
            self.sendMessage('Done.',chatId)
        
        elif command.startswith('price'):
            parts = command.upper().split()
            if len(parts) < 2:
                self.sendMessage("Invalid command", chatId)
                return
            fsym = parts[1]
            tsym = self.DEFAULT_FIAT
            if len(parts) > 2:
                tsym = parts[2]
            if not self.Repository.isPricePairValid(fsym, tsym):
                self.sendMessage("Invalid symbols {} {}".format(fsym,tsym), chatId)
                return

            price = self.get_price(fsym, tsym)
            resp = '1 {} = {} {}'.format(self.get_symbols()[fsym], self.format_price(price),tsym)
            self.sendMessage(resp, chatId)

        elif command.startswith('lower') or command.startswith('higher'):
            parts = command.upper().split()
            if len(parts) < 3 or len(parts) > 4:
                self.sendMessage("Invalid command", chatId)
                return
            op = parts[0]
            fsym = parts[1]
            if not fsym in self.get_symbols().keys():
                self.sendMessage('Invalid symbol "{}"'.format(fsym), chatId)
                return
            try:
                target = float(parts[2])
            except ValueError:
                self.sendMessage('Invalid number "{}"'.format(parts[2]), chatId)
                return
            tsym = parts[3] if len(parts) > 3 else self.DEFAULT_FIAT
            if tsym == "SAT" or tsym== "SATS":
                target=target/(100.0*1000.0*1000.0)
                tsym="BTC"

            if tsym not in self.Repository.TSYMS:
                self.sendMessage('Invalid symbol {}'.format(tsym), chatId)
                return

            if 'alerts' not in self.db:
                self.db['alerts'] = {}
            alerts = self.db['alerts'][chatId] if chatId in self.db['alerts'] else {}
            if fsym in alerts:
                alert = alerts[fsym]
                if op in alert and type(alert[op]) is dict:
                    opObj = alert[op]
                    if tsym in opObj:
                        opObj[tsym].add(target)
                    else:
                        opObj[tsym] = set([target])
                else:
                    alert[op] = {tsym: set([target])}
            else:
                alerts[fsym] = {op: {tsym: set([target])}}
            self.db['alerts'][chatId] = alerts
            msg = 'Notification set for {} {} {} {}.'.format(
                self.get_symbols()[fsym], 'below' if op == 'LOWER' else 'above', self.format_price(target), tsym)
            self.sendMessage(msg, chatId)
        else:
            self.sendMessage('Unknown command', chatId)

    def processMessage(self, message):
        text = message['text']
        chatId = message['chat']['id']
        if('entities' in message and message['entities'][0]['type'] == 'bot_command'):
            self.handleBotCommand(message)
        else:
            self.sendMessage(f'Invalid command {text}', chatId)

    def removeAlert(self, fsym, tsym, target, chatId, op):
        alerts = self.db['alerts']
        alerts[chatId][fsym][op][tsym].remove(target)
        if len(alerts[chatId][fsym][op][tsym]) == 0:
            alerts[chatId][fsym][op].pop(tsym)
            if len(alerts[chatId][fsym][op]) == 0:
                alerts[chatId][fsym].pop(op)
                if len(alerts[chatId][fsym]) == 0:
                    alerts[chatId].pop(fsym)
                    if len(alerts[chatId]) == 0:
                        alerts.pop(chatId)

    def processAlerts(self):
        if 'alerts' not in self.db:
            return
        higher = 'HIGHER'
        lower = 'LOWER'
        alerts = self.db['alerts']
        toRemove = []
        for chatId in alerts:
            for fsym in alerts[chatId]:
                ops = alerts[chatId][fsym]
                for op in ops:
                    tsyms = ops[op]
                    for tsym in tsyms:
                        targets = tsyms[tsym]
                        price = self.get_price(fsym, tsym)
                        for target in targets:
                            if op == lower and price < target or op == higher and price > target:
                                self.sendMessage('{} is {} {} at {} {}'.format(self.get_symbols()[fsym],
                                'below' if op == lower else 'above', self.format_price(target), self.format_price(price), tsym), chatId)
                                toRemove.append((fsym, tsym, target, chatId, op))

        for tr in toRemove:
            self.removeAlert(tr[0], tr[1], tr[2], tr[3], tr[4])
    
    def getUpdates(self):
        offset = self.last_update+1
        url = self.getTgUrl('getUpdates')
        r = requests.post(
            url=url, data={'offset': offset, 'limit': 100, 'timeout': 9})
        updates = r.json()
        if not 'ok' in updates or not updates['ok']:
            return None
        return updates['result']

    def init(self):
        try:
            with open(self.DB_FILENAME, 'rb') as fp:
                self.db = pickle.load(fp)
        except:
            self.db = {}
        self.log("db at start:\n {}".format(self.db))
        self.last_update = self.db['last_update'] if 'last_update' in self.db else 0

    def persist_db(self):
        with open(self.DB_FILENAME, 'wb') as fp:
            pickle.dump(self.db, fp)