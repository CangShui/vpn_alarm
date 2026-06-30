FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码及数据文件
COPY app.py .
COPY collector.py .
COPY config_manager.py .
COPY database.py .
COPY geo_resolver.py .
COPY notifier.py .
COPY GeoLite2-City.mmdb .
COPY static/ static/
COPY templates/ templates/

EXPOSE 5000

# 容器启动时直接运行应用
CMD ["python", "app.py"]
