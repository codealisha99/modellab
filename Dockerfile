FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home lab
COPY --chown=lab:lab app ./app
USER lab
ENV PORT=8005 CHECKPOINT_DIR=/tmp/checkpoints
EXPOSE 8005
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8005')+'/health',timeout=3)"
CMD ["python", "-m", "app.run"]
