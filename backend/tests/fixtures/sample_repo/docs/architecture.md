# Arquitectura

La app tiene un cliente Flutter, un servidor Node.js y scripts de mantenimiento en Python.

## Autenticación

El inicio de sesión se valida en `AuthRepository.login`, que comprueba el formato del correo
antes de llamar a `/auth/login`.

## Inventario

El script `sync_inventory.py` sincroniza el stock del almacén con la tienda online.
