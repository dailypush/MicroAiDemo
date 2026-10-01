FROM python:3.12-slim
WORKDIR /demo
COPY app /demo/app
COPY tests /demo/tests
COPY workshop /demo/workshop
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "app.server"]
