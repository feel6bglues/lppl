# -*- coding: utf-8 -*-

class LPPLException(Exception):
    pass


class DataValidationError(LPPLException):
    pass


class DataFetchError(LPPLException):
    pass


class DataNotFoundError(LPPLException):
    pass


class ComputationError(LPPLException):
    pass


class ConfigurationError(LPPLException):
    pass
