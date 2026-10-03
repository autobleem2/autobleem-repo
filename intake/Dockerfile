# The tester portal's intake service (intake/README.md). Built and run by docker/repo/compose.yml next to the site.
FROM python:3.12-slim
WORKDIR /srv/intake
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10002 intake && mkdir -p /data && chown intake /data
USER intake
EXPOSE 8000
# no --proxy-headers: the client address is taken by app/main.py itself (README, "Running it")
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
