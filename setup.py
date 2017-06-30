#!/usr/bin/env python3.6

# coding=utf-8

from setuptools import setup

setup(
    name='isclib',
    version='0.20',
    description='ISC: Inter-service communication layer for Python. Compatible with gevent.',
    author="Andrew Dunai",
    author_email='andrew@dun.ai',
    url='https://github.com/and3rson/isc',
    license='GPLv3',
    packages=['isc'],
    include_package_data=True,
    install_requires=['setuptools', 'pika', 'kombu'],
    zip_safe=False,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    keywords='rpc,python2,python3,python,gevent,amqp,pika,kombu',
)
