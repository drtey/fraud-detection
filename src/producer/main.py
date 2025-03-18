import os
from confluent_kafka import Producer
from dotenv import load_dotenv
import logging

logging.basicConfig(
    format="%(asctime)s - %(module)s - %(message)s",
    level=logging.INFO
)

logger = logging.getlogger(__name__)

load_dotenv(dotenv_path="/app/.env")

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

if __name__ == "__main__":
    producer = TransactionProducer()
    producer.run_continous_production()