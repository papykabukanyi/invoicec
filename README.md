# Hempire Invoice Generator

A modern invoice generation system built with Flask, featuring:

- Professional PDF invoice generation
- Email delivery of invoices
- Paid invoice marking
- Redis storage for invoice data

## Features

- Create and customize invoices with company information
- Add multiple line items to invoices
- Send invoices directly via email
- Download invoices as PDF
- Mark invoices as paid and send paid confirmations

## Deployment

This application is configured for deployment on Railway.

## Environment Variables

The following environment variables need to be set:

- `EMAIL_ADDRESS`: Gmail address for sending invoices
- `EMAIL_PASSWORD`: App password for Gmail
- `REDIS_URL`: Connection URL for Redis database

## Local Development

1. Create a virtual environment: `python -m venv venv`
2. Activate: `venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r Requirements.txt`
4. Run: `python app.py`

## Deployment on Railway

The app is configured to deploy on Railway with:
- Procfile for Gunicorn configuration
- railway.toml for deployment settings
- Dockerfile for containerized deployment

## License

Copyright © 2025 Hempire Enterprise
