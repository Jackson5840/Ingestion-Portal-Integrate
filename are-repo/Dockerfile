FROM ubuntu:22.04

LABEL maintainer="bljungqu@gmu.edu"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y python3-pip python3-dev libopenblas-base libomp-dev zlib1g-dev libjpeg-dev mysql-client postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

WORKDIR /app

RUN pip3 install --no-cache-dir -r /app/requirements.txt

# copy files required for the app to run
COPY app.py /app/
COPY are/ /app/are/

ADD ui/ /app/ui/




ENTRYPOINT [ "flask" ]

ENV FLASK_APP=app.py
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8


# tell the port number the container should expose
EXPOSE 5000

# run the application
CMD ["run", "--host", "0.0.0.0"]
