# The tester portal's intake service (intake/README.md). Built and run by docker/repo/compose.yml next to the site.
FROM python:3.12-slim
WORKDIR /srv/intake
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# gid 10050 "portal" is shared with the admin service (admin/Dockerfile): the data volume is group-writable
RUN groupadd --gid 10050 portal && useradd --system --uid 10002 --gid 10050 intake \
    && mkdir -p /data && chown intake:portal /data && chmod 2770 /data
USER intake
EXPOSE 8000
# no --proxy-headers: the client address is taken by app/main.py itself (README, "Running it")
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
