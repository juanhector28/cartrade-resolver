# CarTrade Operaciones | Bandeja privada de solicitudes

**Estado:** implementación en PR #135; feature deshabilitada, sin despliegue ni solicitudes reales.

## Ubicación propuesta
- **Ruta backend implementada:** `GET /ops/solicitudes` dentro del servicio resolver.
- **URL objetivo de producto:** `https://cartrade.live/ops/solicitudes`. Esto **todavía requiere** configurar el hosting de Netlify para enrutar `/ops/*` hacia el backend, o servir un frontend dedicado que emplee la API privada. No afirmar que esa URL ya existe.
- **API privada:** `GET /ops/api/solicitudes` (50 solicitudes por página, max 100) y `PATCH /ops/api/solicitudes/{request_id}`.

## Qué verá el operador
- Fecha, vehículo, precio, fuente/enlace original, número WhatsApp.
- Estados manuales: `received` (Nueva), `in_review` (En gestión), `contacted` (Contactado), `closed` (Cerrada).
- Enlace a WhatsApp por solicitud, abierto **solo** al pulsar el operador. Ninguna notificación automática a comprador o vendedor.
- El panel no permite crear créditos ni modificar el inventario de Atlas.

## Protección actual
- Activación independiente: `BUYER_OPS_ENABLED=1`; **por defecto desactivado**.
- Se exige `BUYER_OPS_TOKEN_SHA256` (64 caracteres hexadecimales que corresponden al SHA-256 de un token aleatorio de 32+ caracteres).
- Header API: `Authorization: Bearer <token>`; el token se mantiene solo en RAM en la pestaña, no se guarda en `localStorage`, `sessionStorage`, cookies ni URL.
- Sin token válido la API devuelve HTTP 401. Si faltan configuración/DB: HTTP 503. Si la función está desactivada: HTTP 404.
- `Cache-Control: no-store`, CSP restringida, sin HTML generado desde datos de terceros.
- Consultas efectuadas mediante el rol de servicio server-side, nunca en navegador; solo tabla `buyer_intents`, no `scraped_listings`.
- Sin dependencias nuevas de Router.

## Bloqueos antes de habilitar
1. Completar las barreras de `ops/BUYER_INTENTS_RELEASE.md`: privacidad, retención/borrado de datos, antispam, migración aprobada.
2. Para operaciones reales, sustituir/fortalecer el token compartido con **identidades individuales de operador**, permisos y registro de actividad; no publicar información de contacto sin este control.
3. Revisar acceso de red, HTTPS, política de CORS y proxy de Netlify si se utiliza `cartrade.live/ops`.
4. Probar con datos ficticios la respuesta 401, paginación, cambio de estado, entrada duplicada y fallo de Supabase en entorno privado.
5. Aprobar configuración y rollout explícitamente. PR permanece draft y flags OFF.

## Validación automatizada
`tests/test_paste_link_buyer_ops.py`: API desactivada, clave inválida, sin cliente expuesto, lectura, actualización, paginación y errores sin fuga de PII.
