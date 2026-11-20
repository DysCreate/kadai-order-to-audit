FROM python:3.12-slim
WORKDIR /app
COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir -r requirements/base.txt
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
