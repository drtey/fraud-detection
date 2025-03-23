# Fraud Detection Model Training Pipeline

This project sets up a daily training pipeline for a fraud detection model using Apache Airflow. The pipeline validates the environment, trains the model with XGBoost, and tracks experiments with MLFlow. The pipeline ensures the model stays updated with the latest transaction data from Kafka.

## Table of Contents

- Overview
- Features
- Folder Structure
- Setup
- Usage
- Contributing
- Credits
- License

## Overview

The fraud detection model training pipeline is designed to automate the process of training a machine learning model to detect fraudulent transactions. The pipeline is orchestrated using Apache Airflow and includes tasks for environment validation, model training, and resource cleanup.

## Features

- **Daily Training**: The model is trained daily to ensure it stays up-to-date with the latest data.
- **Environment Validation**: Ensures all necessary configurations and environment variables are set before training.
- **Cleanup**: Cleans up temporary files after training to maintain a clean workspace.
- **Experiment Tracking**: Uses MLFlow to track experiments and model versions.
- **Dockerized Setup**: The entire setup is containerized using Docker for easy deployment and management.

## Folder Structure

```
.
├── airflow
│   ├── Dockerfile
│   └── requirements.txt
├── airflow-logs.txt
├── airflow-webserver-logs.txt
├── config
├── config.yaml
├── dags
│   ├── training_dag.py
│   └── training.py
├── docker-compose.yml
├── init-multiple-dbs.sh
├── logs
├── mlflow
│   ├── Dockerfile
│   └── requirements.txt
├── models
├── plugins
├── producer
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── .env
├── config.yaml
├── docker-compose.yml
├── init-multiple-dbs.sh
└── wait-for-it.sh
```

## Setup

### Prerequisites

- Docker
- Docker Compose

### Steps

1. **Clone the repository**:
    ```sh
    git clone https://github.com/yourusername/fraud-detection.git
    cd fraud-detection
    ```

2. **Set up the environment**:
    ```sh
    cp .env.example .env
    cp config.yaml.example config.yaml
    ```

3. **Start the services**:
    ```sh
    docker-compose up
    ```

4. **Access Airflow**:
    Open your browser and go to `http://localhost:8080` to access the Airflow web interface.

## Usage

### Airflow DAG

The main DAG for the training pipeline is defined in `dags/training_dag.py`. It includes the following tasks:

- **validate_environment**: Validates the environment by checking for necessary configuration files.
- **execute_training**: Executes the model training using the `_train_model` function.
- **cleanup_resources**: Cleans up temporary files after training.

### Training Script

The training script is defined in `dags/training.py`. It includes the `FraudDetectionTraining` class, which handles the training process, including loading configurations, validating the environment, and setting up MLFlow for experiment tracking.

## Credits

This project is based on the work of [airscholar](https://github.com/airscholar/). I have used their project to learn and extend the content for this project.
