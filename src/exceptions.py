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


class WyckoffError(LPPLException):
    pass


class BCNotFoundError(WyckoffError):
    pass


class InvalidInputDataError(WyckoffError):
    pass


class ImageProcessingError(WyckoffError):
    pass


class FusionConflictError(WyckoffError):
    pass


class RuleEngineError(WyckoffError):
    pass
