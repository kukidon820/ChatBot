# arbitrage_bot.py

import os
import time
import logging
import csv
import zipfile
from binance.client import Client
import telebot
from telebot.types import ReplyKeyboardMarkup
import threading
import json
from dotenv import load_dotenv


class ArbitrageBot:
    def __init__(self):
        # Получаем API-ключи и токен Telegram из переменных окружения
        dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
        load_dotenv(dotenv_path)
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")
        self.telegram_token = os.getenv("TELEGRAM_TOKEN")

        print(self.api_key, self.secret_key, self.telegram_token)
        if not self.api_key or not self.secret_key or not self.telegram_token:
            raise ValueError("Не установлены необходимые переменные окружения!")

        self.client = Client(self.api_key, self.secret_key)
        self.bot = telebot.TeleBot(self.telegram_token)
        self.running = False
        self.min_spread = 0.01  # Минимальный спред (1%)
        self.fee = 0.001  # Комиссия (0.1%)
        self.chat_id = self.load_chat_id()  # Загрузка chat_id из файла
        self.initial_deposit = 1000  # Изначальный депозит в USDT

        # Список монет из вашего документа "монеты в паре с BTC.pdf"
        self.btc_pairs = [
            "1INCH", "AAVE", "ACA", "ACHI", "ADA", "ADX", "AEVO", "ALGO", "ALPHA", "ALT", "ANKR", "API3", "APT",
            "ARB", "ARPA", "AR", "ARKM", "ATOM", "AUCTION", "AUDIO", "AUX", "BANANA", "BAT", "BCH", "BEU", "BERA", "BICO",
            "BNB", "CAKE", "CELO", "CELR", "CFX", "CHR", "COMP", "COTI", "CTK", "CTSI", "CTXC", "CYBER", "DATA", "DIA",
            "DODO", "DOGE", "DOT", "EGLD", "ENJ", "ENS", "EOS", "ETC", "ETH", "GALA", "GAS", "GLM", "GMT", "GRT", "HIVE",
            "ICP", "ICX", "IMX", "IOI", "IOTA", "IOTX", "KAVA", "KDA", "KNC", "KSM", "LAYER", "LINK", "LOKA", "LPT", "LRC",
            "LSK", "LTC", "MAGIC", "MANA", "MASK", "MAV", "MC", "MIR", "MINA", "MKR", "MOVE", "MTL", "NEAR", "NEXO", "NKN",
            "OG", "ONE", "ONG", "ONT", "OP", "ORDI", "PEOPLE", "PHB", "PIVX", "POLY", "PORTAL", "PYR", "QTUM", "RARE", "REEF", "REN",
            "RLC", "RONIN", "ROSE", "RSR", "RUNE", "RVN", "SAND", "SANTOS", "SCRT", "SHIB", "SKL", "SLFI", "SOL", "STEEM",
            "STG", "STORJ", "STRAX", "SUI", "SUSHI", "TERRAUSD", "THETA", "TRON", "TRU", "UNI", "VIDT", "WAVES", "WAXP", "WOO",
            "XLM", "XNO", "XRP", "XTZ", "YFI", "ZEC", "ZEN", "ZIL", "TON"
        ]

        logging.basicConfig(filename='arbitrage.log', level=logging.INFO, 
                          format='%(asctime)s - %(levelname)s - %(message)s')

    def start(self):
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            self.chat_id = message.chat.id
            self.save_chat_id()  # Сохраняем chat_id в файл
            markup = self.create_keyboard()
            self.bot.send_message(chat_id=self.chat_id, text="Бот запущен.", reply_markup=markup)

        @self.bot.message_handler(commands=['test'])
        def handle_test(message):
            self.chat_id = message.chat.id
            if not self.chat_id:
                self.bot.send_message(chat_id=message.chat.id, text="Не удалось определить ваш чат. Попробуйте снова.")
                return
            
            prices = self.get_filtered_prices()
            spreads = self.calculate_spreads(prices)

            if spreads:
                for spread in spreads:
                    forward_profit = self.initial_deposit * spread['forward_spread']
                    message_part = (
                        f"Тестовая связка: USDT → {spread['coin']} → BTC → USDT\n"
                        f"Спред: {spread['forward_spread']*100:.2f}%\n"
                        f"Прибыль: {forward_profit:.2f} USDT\n"
                    )
                    self.bot.send_message(chat_id=self.chat_id, text=message_part)
            else:
                self.bot.send_message(chat_id=self.chat_id, text="На данный момент связок нет.")

        @self.bot.message_handler(func=lambda message: True)
        def handle_menu(message):
            if not self.chat_id:
                self.bot.send_message(chat_id=message.chat.id, text="Сначала запустите бота командой /start")
                return

            if message.text.strip().lower() == "старт":
                if not self.running:
                    self.running = True
                    self.bot.send_message(chat_id=self.chat_id, text="Анализ запущен")
                    threading.Thread(target=self.analyze).start()  # Запуск анализа в отдельном потоке
                else:
                    self.bot.send_message(chat_id=self.chat_id, text="Анализ уже запущен")

            elif message.text.strip().lower() == "стоп":
                self.running = False  # Остановка анализа
                self.bot.send_message(chat_id=self.chat_id, text="Анализ остановлен")

            elif message.text.strip().lower() == "скачать архив":
                try:
                    spreads = self.calculate_spreads(self.get_filtered_prices())
                    if not spreads:
                        self.bot.send_message(chat_id=self.chat_id, text="Нет данных для создания отчета.")
                        return

                    # Создание CSV отчета
                    with open('arbitrage_report.csv', mode='w', newline='', encoding='utf-8') as file:
                        writer = csv.writer(file)
                        writer.writerow(["Coin", "Forward Spread", "Initial Deposit", "Final Balance", "Profit"])
                        for spread in spreads:
                            initial_deposit = self.initial_deposit
                            final_balance = initial_deposit * (1 + spread['forward_spread'])
                            profit = final_balance - initial_deposit
                            writer.writerow([
                                spread['coin'],
                                spread['forward_spread'] * 100,
                                initial_deposit,
                                final_balance,
                                profit
                            ])

                    # Создание ZIP-архива
                    zip_filename = 'arbitrage_data.zip'
                    with zipfile.ZipFile(zip_filename, 'w') as zipf:
                        if os.path.exists('arbitrage.log'):
                            zipf.write('arbitrage.log')
                        else:
                            self.bot.send_message(chat_id=self.chat_id, text="Лог-файл отсутствует.")

                        if os.path.exists('arbitrage_report.csv'):
                            zipf.write('arbitrage_report.csv')
                        else:
                            self.bot.send_message(chat_id=self.chat_id, text="CSV отчет отсутствует.")

                    # Отправка ZIP-архива
                    if os.path.exists(zip_filename):
                        with open(zip_filename, 'rb') as file:
                            self.bot.send_document(chat_id=self.chat_id, document=file, caption="Арбитражная связка найдена!")
                    else:
                        self.bot.send_message(chat_id=self.chat_id, text="ZIP-архив не был создан.")

                    # Удаление временных файлов
                    if os.path.exists(zip_filename):
                        os.remove(zip_filename)
                    if os.path.exists('arbitrage_report.csv'):
                        os.remove('arbitrage_report.csv')

                except Exception as e:
                    self.bot.send_message(chat_id=self.chat_id, text=f"Ошибка при создании архива: {e}")
                    logging.error(f"Ошибка при создании архива: {e}")

        self.bot.polling()

    def create_keyboard(self):
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)  # Создаем клавиатуру
        markup.add("Старт", "Стоп", "Скачать архив")  # Добавляем кнопки
        return markup

    def analyze(self):
        while self.running:  # Проверяем состояние self.running
            try:
                logging.info("Начало анализа цен...")
                prices = self.get_filtered_prices()
                spreads = self.calculate_spreads(prices)

                if spreads:
                    self.send_results(spreads)
                else:
                    logging.info("Арбитражных возможностей нет.")
                    self.bot.send_message(chat_id=self.chat_id, text="На данный момент арбитражных возможностей нет.")
            
            except Exception as e:
                logging.error(f"Ошибка во время анализа: {e}")
                self.bot.send_message(chat_id=self.chat_id, text=f"Ошибка во время анализа: {e}")
            
            finally:
                time.sleep(60)  # Обновление каждую минуту

    def get_filtered_prices(self):
        """Получение цен только для нужных пар."""
        prices = {}
        try:
            btc_usdt_price = float(self.client.get_symbol_ticker(symbol='BTCUSDT')['price'])
            if btc_usdt_price <= 0:
                logging.error("Цена BTCUSDT некорректна или равна нулю.")
                return {}

            for base_coin in self.btc_pairs:
                btc_pair = f"{base_coin}BTC"
                usdt_pair = f"{base_coin}USDT"

                try:
                    coin_btc_price = float(self.client.get_symbol_ticker(symbol=btc_pair)['price'])
                    usdt_coin_price = float(self.client.get_symbol_ticker(symbol=usdt_pair)['price'])

                    if coin_btc_price > 0 and usdt_coin_price > 0:
                        prices[base_coin] = {
                            'btc_usdt': btc_usdt_price,
                            'usdt_coin': usdt_coin_price,
                            'coin_btc': coin_btc_price
                        }
                except Exception as e:
                    logging.warning(f"Ошибка получения цены для {base_coin}: {e}")

        except Exception as e:
            logging.error(f"Ошибка получения цен: {e}")
        
        logging.info(f"Получены цены для {len(prices)} пар.")
        return prices

    def calculate_spreads(self, prices):
        """Расчет арбитражных связок с учетом ликвидности."""
        spreads = []
        btc_usdt_price = prices.get('BTCUSDT', {}).get('btc_usdt', 0)

        if btc_usdt_price <= 0:
            logging.error("Отсутствует или некорректная цена для пары BTCUSDT")
            return spreads

        logging.info("Поиск арбитражных связок...")

        for base_coin, coin_prices in prices.items():
            usdt_coin_price = coin_prices['usdt_coin']
            coin_btc_price = coin_prices['coin_btc']

            # Расчет прямого пути (USDT → Монета → BTC → USDT)
            coins_bought = (self.initial_deposit / usdt_coin_price) * (1 - self.fee)  # Покупка монеты за USDT
            btc_received = coins_bought * coin_btc_price * (1 - self.fee)  # Продажа монеты за BTC
            final_balance = btc_received * btc_usdt_price * (1 - self.fee)  # Продажа BTC за USDT

            forward_spread = (final_balance / self.initial_deposit) - 1

            # Проверка на наличие ликвидности
            try:
                ticker_info = self.client.get_ticker(symbol=f"{base_coin}BTC")
                volume_24h = float(ticker_info.get('quoteVolume', 0))  # Объем торгов в BTC за 24 часа

                if volume_24h < 100:  # Пропускаем пары с низкой ликвидностью
                    logging.warning(f"Монета {base_coin} имеет низкий объем торгов (<100 BTC). Пропускаем.")
                    continue

                if forward_spread > self.min_spread:
                    spreads.append({
                        'coin': base_coin,
                        'forward_spread': forward_spread,
                        'prices': {
                            'usdt_coin': usdt_coin_price,
                            'btc_usdt': btc_usdt_price,
                            'coin_btc': coin_btc_price
                        }
                    })
                    logging.info(f"Найдена связка: {base_coin} -> Спред: {forward_spread*100:.2f}%")
                else:
                    logging.info(f"Монета {base_coin} не прошла проверку по спреду ({forward_spread*100:.2f}%).")
            except Exception as e:
                logging.error(f"Ошибка расчета для {base_coin}: {e}")

        logging.info(f"Найдено {len(spreads)} арбитражных связок.")
        return spreads

    def send_results(self, spreads):
        """Отправка результатов с разбиением сообщений на части."""
        if not self.chat_id:
            logging.error("Chat ID не установлен. Бот не может отправить сообщение.")
            return

        messages = []
        for spread in spreads:
            forward_profit = self.initial_deposit * spread['forward_spread']

            message_part = (
                f"Арбитражная связка найдена!\n"
                f"Путь: USDT → {spread['coin']} → BTC → USDT\n"
                f"Цена USDT-{spread['coin']}: {spread['prices']['usdt_coin']:.8f}\n"
                f"Цена {spread['coin']}-BTC: {spread['prices']['coin_btc']:.8f}\n"
                f"Цена BTC-USDT: {spread['prices']['btc_usdt']:.2f}\n"
                f"Спред: {spread['forward_spread']*100:.2f}%\n"
                f"Потенциальная прибыль: {forward_profit:.2f} USDT\n"
                f"Комиссия: {self.fee*100:.1f}%\n\n"
            )
            messages.append(message_part)

        # Разбиение большого сообщения на части
        if messages:
            combined_message = ''.join(messages)
            chunks = [combined_message[i:i+4000] for i in range(0, len(combined_message), 4000)]

            for chunk in chunks:
                self.bot.send_message(chat_id=self.chat_id, text=chunk)

    def save_chat_id(self):
        """Сохранение chat_id в файл."""
        if self.chat_id:
            with open('chat_id.json', 'w') as f:
                json.dump({'chat_id': self.chat_id}, f)

    def load_chat_id(self):
        """Загрузка chat_id из файла."""
        if os.path.exists('chat_id.json'):
            with open('chat_id.json', 'r') as f:
                data = json.load(f)
                return data.get('chat_id', None)
        return None


if __name__ == '__main__':
    load_dotenv()
    bot = ArbitrageBot()
    bot.start()
