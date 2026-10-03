# The admin panel's service (admin/README.md). Built and run by docker/repo/compose.yml next to the site.
FROM python:3.12-slim
WORKDIR /srv/admin
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# gid 10050 "portal" is shared with the intake service (intake/Dockerfile) for the portal data volume
RUN groupadd --gid 10050 portal && useradd --system --uid 10001 --groups portal admin \
    && mkdir -p /data && chown admin /data \
    && mkdir -p /intake && chown admin:portal /intake && chmod 2770 /intake
USER admin
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
