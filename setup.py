# coding=utf-8

from setuptools import setup

setup(
    name='isclib',
    version='0.1',
    description='ISC: Inter-service communication layer for Python.',
    author="Andrew Dunai",
    author_email='andrew@dun.ai',
    url='https://github.com/and3rson/isc',
    license='GPLv3',
    packages=['isc'],
    include_package_data=True,
    install_requires=['setuptools', 'gevent', 'pika'],
    zip_safe=False,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GPLv3 License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    keywords='rpc,python2,python3,python,gevent,amqp,pika',
)
