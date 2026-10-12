# CarTrade: pasar de pruebas sintéticas a solicitudes reales

**Estado: bloqueado, NO habilitar en producción.** La URL
`https://bright-dragon-cd29a3.netlify.app` continúa usando una función
que solo admite un registro ficticio. El sitio `cartrade.live` permanece
independiente.

## Lo que ya está probado
- Navegador móvil y escritorio → Edge Function Supabase → registro sintético
  inmutable → confirmación de prueba.
- 0 solicitudes reales.
- RLS y grants impiden lectura/escritura pública en las tablas de contactos.
- Endpoint de prueba rechaza payloads con WhatsApp y dominios de origen distintos.

## Bloqueos antes de recibir contactos reales
1. Crear widget [Cloudflare Turnstile](https://dash.cloudflare.com/?to=/:account/turnstile),
   limitado al hostname **bright-dragon-cd29a3.netlify.app**.
   El site key es público y pertenece al HTML; el **secret key nunca debe
   aparecer en GitHub, el HTML ni en un chat**. Se instala como variable
   protegida del servicio backend en el entorno correspondiente.
2. Configurar una capa de cuotas **compartidas/persistentes** contra spam.
   El componente `app/link_first_turnstile.py` exige un limitador externo y
   rechaza llamadas sin configuración. Requiere probar umbrales y controles
   contra abuso bajo NAT, proxies y tráfico legítimo.
3. Integrar el widget en un nuevo HTML de candidato, enviar
   `turnstile_token` al backend y contrastar `success`, `hostname` y
   `action=cartrade_link_first` en el servidor. Los tokens son de un solo
   uso y expiran; reiniciar el widget ante fallos.
4. Aprobar finalidad de tratamiento, texto de consentimiento para
   WhatsApp, plazos de conservación, acceso de operadores,
   procedimientos de eliminación y política de privacidad.
5. Configurar receptor privado, secretos y un equipo responsable de
   procesar solicitudes. Validar con datos ficticios que el recibo de
   aceptación solo aparece tras escritura confirmada.
6. Activar solo con aprobación explícita, monitoreo, interruptor de
   emergencia y rollback probado. No enviar mensajes automáticamente
   a bancos, compradores ni vendedores.

## Pruebas actuales de seguridad
`tests/test_link_first_turnstile.py` simula respuestas de Cloudflare
válidas, inválidas, tokens ausentes, fallo de red, rate limit y discrepancias
de hostname/action. No requiere credenciales ni realiza peticiones reales.
`app/link_first_intake.py` permanece sin montar y
`LINK_FIRST_INTAKE_ENABLED` debe permanecer en 0.

No confundir el flujo de prueba existente con la aceptación de contactos
reales. El éxito actual confirma conectividad y aislamiento, no cumplimiento
legal ni preparación operativa.
