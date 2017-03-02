test:
	coverage erase && coverage run -m pytest isc/ --fulltrace && coverage report
