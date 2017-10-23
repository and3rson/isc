FROM python:3.6.3-jessie
MAINTAINER Andrew Dunai

# Enable edge repo
#RUN sed -i -e 's/v3\.\d/v3.6/g' /etc/apk/repositories

#RUN apk add --update py3-gevent
RUN mkdir /home/isc

COPY ./requirements /home/isc/requirements

WORKDIR /home/isc

# Install requirements
RUN \
    python3.6 -m pip install -r ./requirements/test.txt

COPY ./.flake8 /home/isc
COPY ./pytest.ini /home/isc
COPY ./isc /home/isc/isc

