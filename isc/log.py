import logging
# import coloredlogs

LEVEL = logging.DEBUG

FORMAT = '%(asctime)-15s : %(levelname)-8s : %(message)s'
logging.basicConfig(format=FORMAT)
# logging.addLevelName(logging.DEBUG, 'DBG')
# logging.addLevelName(logging.DEBUG, 'ERR')
logger = logging.getLogger('ipc')
logger.level = LEVEL
# handler = logging.StreamHandler()
# logger.addHandler(handler)
# handler.setFormatter(ColoredFormatter())

# coloredlogs.install(level=LEVEL, logger=logger)

debug = logger.debug
info = logger.info
warning = logger.warning
warn = logger.warn
error = logger.error
