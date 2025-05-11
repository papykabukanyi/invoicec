FROM python:3.11-slim

WORKDIR /app

COPY Requirements.txt .
RUN pip install -r Requirements.txt

COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Make port 8000 available for the app
EXPOSE 8000

# Run gunicorn when the container launches
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
