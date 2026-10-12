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
- Autenticación individual con Supabase Auth: correo de operador registrado + código temporal (OTP); backend verifica token contra Supabase Auth y membresía activa en `buyer_ops_staff`. No existen operadores habilitados por defecto.
- `SUPABASE_PUBLISHABLE_KEY` y `SUPABASE_URL` alimentan un cliente Auth nuevo por solicitud, aislado del cliente administrativo usado para consultar la tabla. El publishable key nunca se sustituye por service-role en el navegador.
- El equipo debe provisionar cada cuenta en Supabase Auth, con su `auth.users.id`, email y una fila `buyer_ops_staff` activa. La plantilla de correo OTP debe incluir `{{ .Token }}` y la entrega de correo debe probarse antes de habilitar.
- API: `POST /ops/auth/start` envía código únicamente a personal habilitado sin revelar si un correo está autorizado. `POST /ops/auth/verify` comprueba el código y pertenencia al equipo. Las consultas privadas exigen `Authorization: Bearer <access_token>`; el token solo existe en RAM, no en `localStorage`, `sessionStorage`, cookies ni URL.
- Sin token válido la API devuelve HTTP 401. Sin membresía activa: HTTP 403. Si faltan configuración/DB: HTTP 503. Si está desactivada: HTTP 404.
- `Cache-Control: no-store`, CSP restringida, sin HTML generado desde datos de terceros.
- Consultas efectuadas mediante el rol de servicio server-side, nunca en navegador; solo tabla `buyer_intents`, no `scraped_listings`.
- Sin dependencias nuevas de Router.

## Bloqueos antes de habilitar
1. Completar las barreras de `ops/BUYER_INTENTS_RELEASE.md`: privacidad, retención/borrado de datos, antispam, migración aprobada.
2. **Identidades individuales implementadas en el código**, pendientes de alta de usuarios autorizados y entrega de correo OTP. Para habilitación comercial, complementar con registros de auditoría, revocación de operadores y monitoreo de accesos.
3. Revisar acceso de red, HTTPS, política de CORS y proxy de Netlify si se utiliza `cartrade.live/ops`.
4. Probar con datos ficticios la respuesta 401, paginación, cambio de estado, entrada duplicada y fallo de Supabase en entorno privado.
5. Revisar secretos en Render del workspace correcto y publicar URL vía proxy/redirect Netlify en preview. No exponer el servicio administrativo públicamente con flags activos sin restricción de acceso y pruebas.
6. Aprobar configuración y rollout explícitamente. PR permanece draft y flags OFF.

## Validación automatizada
`tests/test_paste_link_buyer_ops.py`: API desactivada, JWT inválido, operador sin membresía, OTP individual, página sin datos, lectura, actualización, paginación y errores sin fuga de PII.

## Supabase: esquema ya provisionado (2026-10-12)
Proyecto de CarTrade existente: tablas `buyer_intents` y `buyer_ops_staff` creadas mediante migraciones no destructivas. Ambas tienen RLS activo, cero políticas de lectura pública y `anon`/`authenticated` sin SELECT. Filas iniciales: cero. No se concedió autorización a ningún operador.
