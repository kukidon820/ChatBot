import os
import time
import logging
import csv
import zipfile
import json
import threading
from binance.client import Client
import telebot
from telebot.types import ReplyKeyboardMarkup

class ArbitrageBot:
    def __init__(self):
        # Получаем API-ключи и токен Telegram из переменных окружения или используем предоставленные
        self.api_key = os.getenv("BINANCE_API_KEY", "d0DvwFbtKOD9clOHd09nbRcgxLctxZcsTq3TszFnUUd4quPDD7Tnk1YQQt0hk8t3")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY", "TmS5XdHjB22kDQG7rFYg31yEgQpHu8dnabP6IgoqGRUVoeaHMBkFknayZpDpMNV9")
        self.telegram_token = os.getenv("TELEGRAM_TOKEN", "7264041289:AAGnNzM8O_0mslIN6S5X4fzmnyIVvwp60z0")

        # Инициализация клиентов Binance и Telegram
        self.client = Client(self.api_key, self.secret_key)
        self.bot = telebot.TeleBot(self.telegram_token)
        
        # Настройки бота
        self.running = False
        self.min_spread = 0.05  # Минимальный спред (5%)
        self.fee = 0.001  # Комиссия (0.1%)
        self.chat_id = self.load_chat_id()  # Загрузка chat_id из файла
        self.initial_deposit = 1000  # Изначальный депозит в USDT
        self.min_volume = 10  # Минимальный объем торгов в BTC за 24 часа

        # Список монет в паре с BTC
        self.btc_pairs = [
            "1INCH", "AAVE", "ACA", "ACHI", "ADA", "ADX", "AEVO", "ALGO", "ALPHA", "ALT", "ANKR", "API3", "APT",
            "ARB", "ARPA", "AR", "ARKM", "ATOM", "AUCTION", "AUDIO", "AUX", "BANANA", "BAT", "BCH", "BEU", "BERA", "BICO",
            "BNB", "CAKE", "CELO", "CELR", "CFX", "CHR", "COMP", "COTI", "CTK", "CTSI", "CTXC", "CYBER", "DATA", "DIA",
            "DODO", "DOGE", "DOT", "EGLD", "ENJ", "ENS", "EOS", "ETC", "ETH", "GALA", "GAS", "GLM", "GMT", "GRT", "HIVE",
            "ICP", "ICX", "IMX", "IOI", "IOTA", "IOTX", "KAVA", "KDA", "KNC", "KSM", "LAYER", "LINK", "LOKA", "LPT", "LRC",
            "LSK", "LTC", "MAGIC", "MANA", "MASK", "MAV", "MC", "MIR", "MINA", "MKR", "MOVE", "MTL", "NEAR", "NEXO", "NKN",
            "OG", "ONE", "ONT", "OP", "ORDI", "PEOPLE", "PHB", "PIVX", "POLY", "PORTAL", "PYR", "QTUM", "RARE", "REEF", "REN",
            "RLC", "RONIN", "ROSE", "RSR", "RUNE", "RVN", "SAND", "SANTOS", "SCRT", "SHIB", "SKL", "SLFI", "SOL", "STEEM",
            "STG", "STORJ", "STRAX", "SUI", "SUSHI", "THETA", "TRON", "TRU", "UNI", "VIDT", "WAVES", "WAXP", "WOO",
            "XLM", "XNO", "XRP", "XTZ", "YFI", "ZEC", "ZEN", "ZIL", "TON"
        ]

        # Настройка логирования
        logging.basicConfig(filename='arbitrage.log', level=logging.INFO, 
                          format='%(asctime)s - %(levelname)s - %(message)s')
        
        logging.info("Бот инициализирован")

    def start(self):
        """Запуск бота и настройка обработчиков сообщений"""
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            self.chat_id = message.chat.id
            self.save_chat_id()  # Сохраняем chat_id в файл
            markup = self.create_keyboard()
            self.bot.send_message(chat_id=self.chat_id, text="Бот запущен. Используйте кнопки для управления.", reply_markup=markup)
            logging.info(f"Бот запущен пользователем {message.chat.id}")

        @self.bot.message_handler(commands=['test'])
        def handle_test(message):
            self.chat_id = message.chat.id
            if not self.chat_id:
                self.bot.send_message(chat_id=message.chat.id, text="Не удалось определить ваш чат. Попробуйте снова.")
                return
            
            logging.info("Запущено тестирование")
            self.bot.send_message(chat_id=self.chat_id, text="Начинаю тестирование...")
            
            try:
                # Получаем цены и рассчитываем спреды
                prices = self.get_filtered_prices()
                spreads = self.calculate_spreads(prices)

                if spreads:
                    # Показываем только топ-3 связки для теста
                    for spread in spreads[:3]:
                        forward_profit = self.initial_deposit * spread['forward_spread']
                        message_part = (
                            f"Тестовая связка: USDT → {spread['coin']} → BTC → USDT\n"
                            f"Спред: {spread['forward_spread']*100:.2f}%\n"
                            f"Прибыль: {forward_profit:.2f} USDT\n"
                            f"Объем торгов (24ч): {spread['volume_24h']:.2f} BTC\n"
                        )
                        self.bot.send_message(chat_id=self.chat_id, text=message_part)
                else:
                    self.bot.send_message(chat_id=self.chat_id, text="На данный момент связок нет.")
            except Exception as e:
                logging.error(f"Ошибка при тестировании: {e}")
                self.bot.send_message(chat_id=self.chat_id, text=f"Ошибка при тестировании: {e}")

        @self.bot.message_handler(func=lambda message: True)
        def handle_menu(message):
            if not self.chat_id:
                self.bot.send_message(chat_id=message.chat.id, text="Сначала запустите бота командой /start")
                return

            text = message.text.strip().lower()
            
            if text == "старт":
                if not self.running:
                    self.running = True
                    self.bot.send_message(chat_id=self.chat_id, text="Анализ запущен")
                    logging.info("Анализ запущен")
                    # Запуск анализа в отдельном потоке
                    threading.Thread(target=self.analyze, daemon=True).start()
                else:
                    self.bot.send_message(chat_id=self.chat_id, text="Анализ уже запущен")

            elif text == "стоп":
                self.running = False  # Остановка анализа
                self.bot.send_message(chat_id=self.chat_id, text="Анализ остановлен")
                logging.info("Анализ остановлен")

            elif text == "скачать архив":
                self.generate_report()

        # Запуск бота
        logging.info("Запуск бота в режиме polling")
        self.bot.polling(none_stop=True)

    def create_keyboard(self):
        """Создание клавиатуры с кнопками"""
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        markup.add("Старт", "Стоп", "Скачать архив")
        return markup

    def analyze(self):
        """Основной цикл анализа цен и поиска арбитражных возможностей"""
        while self.running:
            try:
                logging.info("Начало анализа цен...")
                self.bot.send_message(chat_id=self.chat_id, text="Начинаю анализ цен...")
                
                # Получаем цены и рассчитываем спреды
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
                # Пауза между циклами анализа
                time.sleep(60)  # Обновление каждую минуту

    def get_filtered_prices(self):
        """Получение цен для всех нужных пар с фильтрацией по объему"""
        prices = {}
        try:
            logging.info("Получение цен с Binance...")
            
            # Получаем цену BTC/USDT
            btc_usdt_ticker = self.client.get_symbol_ticker(symbol='BTCUSDT')
            btc_usdt_price = float(btc_usdt_ticker['price'])
            
            if btc_usdt_price <= 0:
                logging.error("Цена BTCUSDT некорректна или равна нулю.")
                return {}
            
            # Сохраняем цену BTC/USDT
            prices['BTCUSDT'] = btc_usdt_price
            
            # Получаем все тикеры за один запрос для оптимизации
            all_tickers = self.client.get_all_tickers()
            ticker_map = {ticker['symbol']: float(ticker['price']) for ticker in all_tickers}
            
            # Получаем статистику за 24 часа для проверки объема
            all_stats_24h = self.client.get_ticker()
            stats_map = {}
            
            for stat in all_stats_24h:
                if 'symbol' in stat and 'quoteVolume' in stat:
                    stats_map[stat['symbol']] = {
                        'volume': float(stat['quoteVolume'])
                    }
            
            # Обрабатываем каждую монету
            for base_coin in self.btc_pairs:
                btc_pair = f"{base_coin}BTC"
                usdt_pair = f"{base_coin}USDT"
                
                # Проверяем, существуют ли обе пары
                if btc_pair in ticker_map and usdt_pair in ticker_map:
                    coin_btc_price = ticker_map[btc_pair]
                    usdt_coin_price = ticker_map[usdt_pair]
                    
                    # Проверяем объем торгов
                    btc_pair_volume = stats_map.get(btc_pair, {}).get('volume', 0)
                    
                    if coin_btc_price > 0 and usdt_coin_price > 0 and btc_pair_volume >= self.min_volume:
                        prices[base_coin] = {
                            'btc_usdt': btc_usdt_price,
                            'usdt_coin': usdt_coin_price,
                            'coin_btc': coin_btc_price,
                            'volume_24h': btc_pair_volume
                        }
            
            logging.info(f"Получены цены для {len(prices) - 1} пар.")  # -1 для BTCUSDT
            return prices
            
        except Exception as e:
            logging.error(f"Ошибка получения цен: {e}")
            return prices

    def calculate_spreads(self, prices):
        """Расчет арбитражных связок с учетом комиссий и ликвидности"""
        spreads = []
        btc_usdt_price = prices.get('BTCUSDT', 0)

        if btc_usdt_price <= 0:
            logging.error("Отсутствует или некорректная цена для пары BTCUSDT")
            return spreads

        logging.info("Поиск арбитражных связок...")

        for base_coin, coin_prices in prices.items():
            # Пропускаем запись BTCUSDT
            if base_coin == 'BTCUSDT':
                continue
                
            usdt_coin_price = coin_prices['usdt_coin']
            coin_btc_price = coin_prices['coin_btc']
            volume_24h = coin_prices.get('volume_24h', 0)

            # Расчет прямого пути (USDT → Монета → BTC → USDT)
            # Шаг 1: Покупка монеты за USDT
            coins_bought = (self.initial_deposit / usdt_coin_price) * (1 - self.fee)
            
            # Шаг 2: Продажа монеты за BTC
            btc_received = coins_bought * coin_btc_price * (1 - self.fee)
            
            # Шаг 3: Продажа BTC за USDT
            final_balance = btc_received * btc_usdt_price * (1 - self.fee)
            
            # Расчет спреда
            forward_spread = (final_balance / self.initial_deposit) - 1
            profit = final_balance - self.initial_deposit

            # Проверка на минимальный спред
            if forward_spread >= self.min_spread:
                spreads.append({
                    'coin': base_coin,
                    'forward_spread': forward_spread,
                    'prices': {
                        'usdt_coin': usdt_coin_price,
                        'btc_usdt': btc_usdt_price,
                        'coin_btc': coin_btc_price
                    },
                    'volume_24h': volume_24h,
                    'final_balance': final_balance,
                    'profit': profit
                })
                logging.info(f"Найдена связка: {base_coin} -> Спред: {forward_spread*100:.2f}%")

        # Сортировка по спреду (от большего к меньшему)
        spreads.sort(key=lambda x: x['forward_spread'], reverse=True)
        
        logging.info(f"Найдено {len(spreads)} арбитражных связок.")
        return spreads

    def send_results(self, spreads):
        """Отправка результатов с разбиением сообщений на части"""
        if not self.chat_id:
            logging.error("Chat ID не установлен. Бот не может отправить сообщение.")
            return

        messages = []
        for spread in spreads:
            forward_profit = spread['profit']
            volume_24h = spread.get('volume_24h', 0)

            message_part = (
                f"Арбитражная связка найдена!\n"
                f"Путь: USDT → {spread['coin']} → BTC → USDT\n"
                f"Цена USDT-{spread['coin']}: {spread['prices']['usdt_coin']:.8f}\n"
                f"Цена {spread['coin']}-BTC: {spread['prices']['coin_btc']:.8f}\n"
                f"Цена BTC-USDT: {spread['prices']['btc_usdt']:.2f}\n"
                f"Спред: {spread['forward_spread']*100:.2f}%\n"
                f"Потенциальная прибыль: {forward_profit:.2f} USDT\n"
                f"Комиссия: {self.fee*100:.1f}%\n"
                f"Объем торгов (24ч): {volume_24h:.2f} BTC\n\n"
            )
            messages.append(message_part)

        # Разбиение большого сообщения на части
        if messages:
            combined_message = ''.join(messages)
            chunks = [combined_message[i:i+4000] for i in range(0, len(combined_message), 4000)]

            for chunk in chunks:
                self.bot.send_message(chat_id=self.chat_id, text=chunk)

    def generate_report(self):
        """Создание и отправка отчета в формате CSV и ZIP"""
        try:
            logging.info("Создание отчета...")
            self.bot.send_message(chat_id=self.chat_id, text="Создаю отчет...")
            
            # Получаем данные для отчета
            prices = self.get_filtered_prices()
            spreads = self.calculate_spreads(prices)
            
            if not spreads:
                self.bot.send_message(chat_id=self.chat_id, text="Нет данных для создания отчета.")
                return
            
            # Создание CSV отчета
            with open('arbitrage_report.csv', mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(["Монета", "Спред (%)", "Начальный депозит (USDT)", 
                                "Конечный баланс (USDT)", "Прибыль (USDT)", "Объем торгов (BTC)"])
                
                for spread in spreads:
                    writer.writerow([
                        spread['coin'],
                        f"{spread['forward_spread'] * 100:.2f}",
                        self.initial_deposit,
                        f"{spread['final_balance']:.2f}",
                        f"{spread['profit']:.2f}",
                        f"{spread.get('volume_24h', 0):.2f}"
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
                    self.bot.send_document(chat_id=self.chat_id, document=file, 
                                          caption="Отчет по арбитражным возможностям")
                logging.info("Отчет успешно отправлен")
            else:
                self.bot.send_message(chat_id=self.chat_id, text="ZIP-архив не был создан.")
            
            # Удаление временных файлов
            if os.path.exists(zip_filename):
                os.remove(zip_filename)
            if os.path.exists('arbitrage_report.csv'):
                os.remove('arbitrage_report.csv')
            
        except Exception as e:
            logging.error(f"Ошибка при создании отчета: {e}")
            self.bot.send_message(chat_id=self.chat_id, text=f"Ошибка при создании отчета: {e}")

    def save_chat_id(self):
        """Сохранение chat_id в файл"""
        if self.chat_id:
            with open('chat_id.json', 'w') as f:
                json.dump({'chat_id': self.chat_id}, f)

    def load_chat_id(self):
        """Загрузка chat_id из файла"""
        if os.path.exists('chat_id.json'):
            with open('chat_id.json', 'r') as f:
                data = json.load(f)
                return data.get('chat_id', None)
        return None


if __name__ == '__main__':
    try:
        bot = ArbitrageBot()
        bot.start()
    except Exception as e:
        logging.critical(f"Критическая ошибка при запуске бота: {e}")
        print(f"Критическая ошибка при запуске бота: {e}")
