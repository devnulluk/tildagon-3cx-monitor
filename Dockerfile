FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home bridge && install -d -o 10001 -g 10001 -m 0700 /data
COPY bridge/bridge ./bridge
USER 10001
EXPOSE 8787
CMD ["python", "-m", "bridge", "--config", "/config/config.json", "--host", "0.0.0.0", "--port", "8787"]
