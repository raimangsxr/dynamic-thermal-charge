FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY entrypoint.sh /usr/local/bin/dynamic-thermal-charge-entrypoint
RUN pip install --no-cache-dir ".[api,mqtt,gpio,db,postgres]"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["/usr/local/bin/dynamic-thermal-charge-entrypoint"]
CMD ["python", "-c", "from dynamic_thermal_charge.entrypoints import run_controller; run_controller()"]
