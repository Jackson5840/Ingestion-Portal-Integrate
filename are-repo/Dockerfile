# our base image
FROM ubuntu:18.04

# Add the PostgreSQL PGP key to verify their Debian packages.
# It should be the same key as https://www.postgresql.org/media/keys/ACCC4CF8.asc

RUN apt-get update -y && \
    apt-get install -y python3-pip python3-dev zlib1g-dev libjpeg-dev


# Install python and pip
MAINTAINER Bengt Ljungquist "bljungqu@gmu.edu"

RUN apt-get update -y && \
    apt-get install -y python3-pip python3-dev libopenblas-base libomp-dev zlib1g-dev libjpeg-dev


# install Python modules needed by the Python app
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
