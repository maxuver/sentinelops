FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --no-create-home --uid 10001 sentinel
USER 10001

CMD ["python", "-m", "app.worker"]
