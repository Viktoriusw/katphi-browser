"""
Esquemas de validación para respuestas del backend.
Previene inyección de datos maliciosos validando la estructura JSON.
"""
from typing import Any, Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Error de validación de esquema"""
    pass


def validate_type(value: Any, expected_type: type, field_name: str = "field") -> None:
    """Valida que un valor sea del tipo esperado"""
    if not isinstance(value, expected_type):
        raise ValidationError(
            f"{field_name} must be {expected_type.__name__}, got {type(value).__name__}"
        )


def validate_dict_schema(data: Dict, schema: Dict[str, tuple], strict: bool = False) -> Dict:
    """
    Valida un diccionario contra un esquema.

    Args:
        data: Datos a validar
        schema: Esquema en formato {campo: (tipo, requerido)}
        strict: Si True, no permite campos adicionales
    Returns:
        Diccionario validado
    Raises:
        ValidationError: Si la validación falla
    """
    if not isinstance(data, dict):
        raise ValidationError(f"Expected dict, got {type(data).__name__}")
    validated = {}

    # Validar campos del esquema
    for field, (expected_type, required) in schema.items():
        if field not in data:
            if required:
                raise ValidationError(f"Required field '{field}' is missing")
            continue
        value = data[field]

        # Permitir None si no es requerido
        if value is None and not required:
            validated[field] = None
            continue
        # Validar tipo
        if not isinstance(value, expected_type):
            raise ValidationError(
                f"Field '{field}' must be {expected_type.__name__}, got {type(value).__name__}"
            )
        validated[field] = value
    # En modo strict, rechazar campos adicionales
    if strict:
        extra_fields = set(data.keys()) - set(schema.keys())
        if extra_fields:
            raise ValidationError(f"Unexpected fields: {extra_fields}")
    else:
        # Agregar campos adicionales si no es strict
        for field, value in data.items():
            if field not in validated:
                validated[field] = value
    return validated


# Esquemas de respuestas del backend

AUTH_RESPONSE_SCHEMA = {
    'access_token': (str, True),
    'refresh_token': (str, True),
    'user_id': (str, True),
    'email': (str, True),
    'expires_at': ((int, float), False),
}

USER_INFO_SCHEMA = {
    'id': (str, True),
    'email': (str, True),
    'name': (str, False),
    'verified': (bool, False),
    'created_at': (str, False),
}

PLUGIN_INFO_SCHEMA = {
    'id': (str, True),
    'name': (str, True),
    'version': (str, True),
    'description': (str, False),
    'enabled': (bool, False),
    'license_type': (str, False),
}

LICENSE_INFO_SCHEMA = {
    'plugin_id': (str, True),
    'is_active': (bool, True),
    'tier': (str, True),
    'expires_at': ((int, float, type(None)), False),
    'trial_ends_at': ((int, float, type(None)), False),
}

PLUGIN_LIST_SCHEMA = {
    'plugins': (list, True),
    'total': (int, False),
}


def validate_auth_response(data: Dict) -> Dict:
    """Valida respuesta de autenticación"""
    try:
        return validate_dict_schema(data, AUTH_RESPONSE_SCHEMA, strict=False)
    except ValidationError as e:
        logger.error(f"Auth response validation failed: {e}")
        raise


def validate_user_info(data: Dict) -> Dict:
    """Valida información de usuario"""
    try:
        return validate_dict_schema(data, USER_INFO_SCHEMA, strict=False)
    except ValidationError as e:
        logger.error(f"User info validation failed: {e}")
        raise


def validate_plugin_info(data: Dict) -> Dict:
    """Valida información de plugin"""
    try:
        return validate_dict_schema(data, PLUGIN_INFO_SCHEMA, strict=False)
    except ValidationError as e:
        logger.error(f"Plugin info validation failed: {e}")
        raise


def validate_license_info(data: Dict) -> Dict:
    """Valida información de licencia"""
    try:
        return validate_dict_schema(data, LICENSE_INFO_SCHEMA, strict=False)
    except ValidationError as e:
        logger.error(f"License info validation failed: {e}")
        raise


def validate_plugin_list(data: Dict) -> Dict:
    """Valida lista de plugins"""
    try:
        validated = validate_dict_schema(data, PLUGIN_LIST_SCHEMA, strict=False)

        # Validar cada plugin en la lista
        if 'plugins' in validated:
            validated_plugins = []
            for plugin in validated['plugins']:
                if isinstance(plugin, dict):
                    validated_plugins.append(validate_plugin_info(plugin))
                else:
                    logger.warning(f"Invalid plugin entry in list: {type(plugin)}")
            validated['plugins'] = validated_plugins
        return validated
    except ValidationError as e:
        logger.error(f"Plugin list validation failed: {e}")
        raise


def safe_validate(data: Any, validator_func, default: Any = None) -> Any:
    """
    Valida datos de forma segura, retornando un valor por defecto si falla.

    Args:
        data: Datos a validar
        validator_func: Función de validación
        default: Valor por defecto si falla la validación
    Returns:
        Datos validados o valor por defecto
    """
    try:
        return validator_func(data)
    except (ValidationError, Exception) as e:
        logger.warning(f"Validation failed, using default: {e}")
        return default
