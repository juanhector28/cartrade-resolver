# Carly · Pega el link · Consolidación del piloto SV

**Entorno:** https://cartrade-paste-link-staging.onrender.com  
**PR de trabajo:** https://github.com/juanhector28/cartrade-resolver/pull/135  
**Estado:** candidato a **piloto técnico** por fuente, **NO autorizado para producción**.

## 1. Qué queda consolidado

- 11 dominios con al menos **3 anuncios individuales distintos** y título, precio anunciado, año y URL de foto provenientes de la ficha. La matriz canónica es [`paste_link_sv_qa_3_per_site.json`](paste_link_sv_qa_3_per_site.json).
- Al menos una fotografía por dominio se cargó en Chromium. **No** se ha validado visualmente cada una de las 33 fotografías.
- Existen fuentes que omiten kilometraje o publican información contradictoria; **no se inventa el dato**.
- 14 dominios permitidos para ensayos manuales en staging: 11 con muestras probadas y 3 pendientes (EasyCar, CrediQ, Eurosport). Otros candidatos siguen deshabilitados.
- Staging no escribe en Supabase, no almacena anuncios ni descarga imágenes; cada consulta verifica robots y valida la ruta concreta.

## 2. Definición del primer lote de piloto

Para cada dominio, el criterio *técnico preliminar* exige:

1. ≥3 URLs distintas y actuales con título, precio anunciado, año y enlace a fotografía.
2. ≥1 fotografía realmente cargada en navegador.
3. Validación de host HTTPS, forma exacta de URL, sin redireccionamientos, sin catálogos ni consultas inseguras.
4. Fallar con un error claro cuando no hay precio o la fuente bloquea acceso.
5. Mantener kilometraje opcional y no resolver divergencias de la fuente inventando datos.

`GET /api/coverage` muestra el estado calculado por fuente. Su contenido deriva de **evidencia histórica registrada**, no es un monitor en vivo de disponibilidad o precio.

## 3. Puertas obligatorias antes de producción

Revisar `paste_link_sv_release_controls.json`. Todas las siguientes puertas siguen **sin aprobar**:

- **Permisos:** confirmar términos de utilización y exposición de datos/fotos de terceros. Que un sitio permita leer `robots.txt` no significa que autorice su explotación comercial.
- **Precio fresco:** corregir la caché en el resolver de producción para que el precio de venta de terceros **no salga de una entrada antigua**. Definir prueba que verifica cambio de precio y caducidad.
- **Seguridad/integración:** uso de API autenticada o proxy correcto, CORS, SSRF, tolerancia de errores, tasa de consulta y aislamiento de la fuente.
- **Operación:** alerta de fallos y cambio de plantilla por sitio, observabilidad por fuente, política de verificación permitida y sin solicitudes repetitivas.
- **Rollback:** feature flags por dominio y protocolo documentado de desactivación inmediata.

La aprobación debe incluir evidencia, propietario responsable y cambio explícito. Un CI verde **no** concede automáticamente autorización de lanzamiento.

## 4. Próximas integraciones

[Cola de 9 oportunidades con evidencia y definición de terminado](paste_link_sv_next_wave.json).

| Prioridad | Fuente | Obstáculo actual | Acción siguiente |
|---|---|---|---|
| P1 | EasyCar | Web dinámica sin detalle visible | Identificar API pública permitida o datos embebidos válidos |
| P2 | Credipro | Vínculo `#vehicle` al catálogo, no URL individual | Demostrar asociación única ID ↔ vehículo y precio |
| P3 | Autosale | Catálogo con identificador de fragmento | Adaptador a identificador individual |
| P4 | Eurosport Autos | Restricción/acceso + cliente JS | Revisar permiso y endpoint |
| P5 | CrediQ | Robots 403 | Revisar acuerdo/acceso |
| P6 | Encuentra24 | HTTP 403 | Canal oficial o permiso |
| P7 | Porsche Finder | Preflight 429 | Revisar acceso antes de nuevas consultas |
| P8 | xAutoMarket | No publica precio verificable | No aceptar precio supuesto |
| P9 | BAC catálogo | `#vehicle` y contenido potencialmente condicionado | Asociación unívoca + permiso |

## 5. Cómo avanzar sin romper Carly

Mantener todas las nuevas adaptaciones en el mismo PR/staging. Extender fuentes de forma controlada, con un mínimo de tres anuncios y un navegador que cargue la foto. Ejecutar diagnósticos externos solo de forma intencional, con reglas de acceso verificadas. No fusionar ni activar producción hasta cumplir las cinco puertas anteriores.

**Próximo sprint técnico:** adaptar la lectura del precio de EasyCar si existe una fuente pública permitida, y prototipar la asociación de ID/vehículo de Credipro y Autosale sin utilizar precios del catálogo por proximidad.
