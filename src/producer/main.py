import os
import signal
import time
import json
from confluent_kafka import Producer
from dotenv import load_dotenv
import logging
import random
from faker import Faker 

logging.basicConfig(
    format="%(asctime)s - %(module)s - %(message)s",
    level=logging.INFO
)

logger = logging.getlogger(__name__)

load_dotenv(dotenv_path="/app/.env")

fake = Faker()

class TransactionProducer():
    def __init__(self):
        self.bootsrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
        self.kafka_username = os.getenv('KAFKA_USERNAME')
        self.kafka_password = os.getenv('KAFKA_PASSWORD')
        self.topic = os.getenv('KAFKA_TOPIC', 'transactions')
        self.running = False

        # confluent kafka config
        self.producer_config = {
            'bootsrap.servers': self.bootsrap_servers,
            'client.id': 'transaction-producer',
            'compression.type': 'gzip',
            'linger.ms': '5',
            'batch.size': 16384
        }

        if self.kafka_username and self.kafka_password:
            self.producer_config.update({
                'security.protocol': 'SASL_SSL',
                'sasl.mechanism': 'PLAIN',
                'sasl.username': self.kafka_username,
                'sasl.password': self.kafka_password
            })
        else:
            self.producer_config['security.protocol'] = 'PLAINTEXT'


        try:
            self.producer = Producer(self.producer_config)
            logger.info("Confluent Kafka producer is initialized!*************")
        except Exception as e:
            logger.error('Failed to initialize confluent kafka producer: {str(e)}')
            raise e
        
        self.compromised_users = set(random.sample(range(1000, 9999), 50)) # 0.5% of total users
        self.high_risk_merchants = ['Quickcash', 'GlobalDigital', 'FastMoneyX']
        self.fraud_pattern_weigths = {
            'account_takeover': 0.4, # fraud cases 40%
            'card_testing': 0.3, # 30%
            'merchant_collusion': 0.2, # 20%
            'geo_anomaly': 0.1 # 10%
        }

        # configure graceful shutdown
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    def delivery_report(self, err, msg):
        if err is not None:
            logger.error(f'Error message delivery failed: {err}')
        else:
            logger.info(f'Message delivered correctly to {msg.topic()} [{msg.partition()}]')

    def send_transaction(self) -> bool:
        try:
            transaction = self.generate_transaction()
            if not transaction:
                return False

            self.producer.produce(
                self.topic,
                key=transaction['transaction_id'],
                value=json.dumps(transaction),
                callback=self.delivery_post
            )

            self.producer.poll(0)  # trigger callbacks
            return True
        except Exception as e:
            logger.error(f'Error producing message: {str(3)}')
            return False

    def run_continous_production(self, interval: float=0.0):
        """" Run continous message production"""
        self.running = True 
        logger.info('Starting producer for topic %s...', self.topic)

        try:
            while self.running:
                if self.send_transaction():
                        time.sleep(interval)
        finally: 
            self.shutdown()

    def shutdown(self, signum=None, frame=None):
        if self.running:
            logging.info('Initiating shutdown...')
            self.running = False

            if self.producer: 
                self.producer.flush(timeout=30)
                self.producer.close()
            logger.info('Producer stopped')

if __name__ == "__main__":
    producer = TransactionProducer()
    producer.run_continous_production()