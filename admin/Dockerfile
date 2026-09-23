# The admin panel's service (admin/README.md). Built and run by docker/repo/compose.yml next to the site.
FROM python:3.12-slim
WORKDIR /srv/admin
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10001 admin && mkdir -p /data && chown admin /data
USER admin
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
