FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY price_monitor price_monitor
RUN pip install --no-cache-dir .
ENV DB_PATH=/data/price_monitor.db
CMD ["python", "-m", "price_monitor"]
