import hashlib
import os
import re
from datetime import datetime

import pandas as pd
import redis
import streamlit as st

# =========================
# Configuración general
# =========================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 horas

st.set_page_config(
    page_title="Asistente Ecommerce con Redis",
    page_icon="🛒",
    layout="wide"
)

# =========================
# Conexión a Redis
# =========================
@st.cache_resource
def conectar_redis():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True
    )

redis_client = conectar_redis()

# =========================
# Datos simulados de pedidos
# =========================
PEDIDOS = {
    "PED-45821": {
        "cliente": "Ana Torres",
        "estado": "En camino",
        "fecha_compra": "2026-05-17",
        "fecha_estimada": "2026-05-22",
        "transportista": "Urbano Express",
        "producto": "Laptop Lenovo IdeaPad 3",
        "total": "S/ 2,499.00"
    },
    "PED-78452": {
        "cliente": "Luis Ramírez",
        "estado": "Preparando pedido",
        "fecha_compra": "2026-05-19",
        "fecha_estimada": "2026-05-24",
        "transportista": "Pendiente de asignación",
        "producto": "Audífonos Bluetooth JBL",
        "total": "S/ 189.90"
    },
    "PED-99310": {
        "cliente": "María López",
        "estado": "Entregado",
        "fecha_compra": "2026-05-12",
        "fecha_estimada": "2026-05-16",
        "transportista": "Olva Courier",
        "producto": "Smart TV Samsung 55 pulgadas",
        "total": "S/ 1,899.00"
    },
    "PED-11220": {
        "cliente": "Carlos Medina",
        "estado": "Retrasado",
        "fecha_compra": "2026-05-15",
        "fecha_estimada": "2026-05-21",
        "transportista": "Urbano Express",
        "producto": "Silla gamer ergonómica",
        "total": "S/ 699.00"
    }
}

# =========================
# Funciones auxiliares
# =========================
def normalizar_texto(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def crear_clave_cache(pregunta: str, numero_pedido: str) -> str:
    texto_base = f"{normalizar_texto(pregunta)}|{numero_pedido.upper().strip()}"
    hash_texto = hashlib.md5(texto_base.encode()).hexdigest()
    return f"consulta_ecommerce:{hash_texto}"


def detectar_categoria(pregunta: str) -> str:
    p = normalizar_texto(pregunta)

    if any(palabra in p for palabra in ["estado", "seguimiento", "donde", "dónde", "ubicacion", "ubicación", "llega", "tracking"]):
        return "seguimiento"
    if any(palabra in p for palabra in ["devolver", "devolucion", "devolución", "cambio", "cambiar", "reembolso"]):
        return "devoluciones"
    if any(palabra in p for palabra in ["cancelar", "anular", "cancelacion", "cancelación"]):
        return "cancelacion"
    if any(palabra in p for palabra in ["pago", "tarjeta", "yape", "plin", "efectivo", "boleta", "factura"]):
        return "pagos"
    if any(palabra in p for palabra in ["dañado", "danado", "roto", "defectuoso", "garantia", "garantía", "reclamo"]):
        return "reclamos"

    return "general"


def generar_respuesta_ia_simulada(pregunta: str, numero_pedido: str) -> tuple[str, str]:
    numero_pedido = numero_pedido.upper().strip()
    categoria = detectar_categoria(pregunta)
    pedido = PEDIDOS.get(numero_pedido)

    if not pedido:
        respuesta = (
            f"No encontré información para el pedido {numero_pedido}. "
            "Verifica que el código esté escrito correctamente. Ejemplo válido: PED-45821."
        )
        return respuesta, categoria

    if categoria == "seguimiento":
        respuesta = (
            f"Tu pedido {numero_pedido} se encuentra en estado: {pedido['estado']}.\n\n"
            f"Producto: {pedido['producto']}\n"
            f"Fecha de compra: {pedido['fecha_compra']}\n"
            f"Fecha estimada de entrega: {pedido['fecha_estimada']}\n"
            f"Transportista: {pedido['transportista']}\n\n"
            "Te recomendamos revisar el estado nuevamente durante el día, ya que la información puede actualizarse."
        )

    elif categoria == "devoluciones":
        respuesta = (
            f"Para solicitar un cambio o devolución del pedido {numero_pedido}, primero verifica que el producto "
            "esté en buen estado, con sus accesorios y empaque original. Luego registra la solicitud desde la sección "
            "'Mis pedidos'. El área de atención evaluará el caso según las políticas de devolución."
        )

    elif categoria == "cancelacion":
        if pedido["estado"] in ["Entregado", "En camino"]:
            respuesta = (
                f"El pedido {numero_pedido} está en estado '{pedido['estado']}', por lo que puede que ya no sea posible cancelarlo directamente. "
                "Puedes comunicarte con atención al cliente para evaluar una devolución o rechazo de entrega."
            )
        else:
            respuesta = (
                f"El pedido {numero_pedido} todavía está en estado '{pedido['estado']}'. "
                "Puedes solicitar la cancelación desde la sección 'Mis pedidos' antes de que pase a despacho."
            )

    elif categoria == "pagos":
        respuesta = (
            f"El pedido {numero_pedido} registra un total de {pedido['total']}. "
            "Los medios de pago disponibles para compras ecommerce suelen incluir tarjeta, billeteras digitales y otros métodos habilitados por la tienda. "
            "Para boleta o factura, revisa el comprobante asociado a tu compra."
        )

    elif categoria == "reclamos":
        respuesta = (
            f"Si el producto del pedido {numero_pedido} llegó dañado, defectuoso o incompleto, registra un reclamo desde 'Mis pedidos'. "
            "Incluye fotos del producto, empaque y comprobante de compra para acelerar la evaluación."
        )

    else:
        respuesta = (
            f"Puedo ayudarte con el pedido {numero_pedido}. Este asistente responde consultas sobre seguimiento, pagos, "
            "cancelaciones, devoluciones y reclamos de pedidos ecommerce."
        )

    return respuesta, categoria


def guardar_historial(pregunta: str, numero_pedido: str, respuesta: str, categoria: str, origen: str):
    registro = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pedido": numero_pedido.upper().strip(),
        "categoria": categoria,
        "origen": origen,
        "pregunta": pregunta,
        "respuesta": respuesta
    }

    redis_client.lpush("historial_consultas", str(registro))
    redis_client.ltrim("historial_consultas", 0, 49)

    redis_client.hincrby("metricas", "total_consultas", 1)
    redis_client.hincrby("metricas", f"categoria:{categoria}", 1)
    redis_client.hincrby("metricas", f"origen:{origen}", 1)


def obtener_metricas():
    metricas = redis_client.hgetall("metricas")
    return {k: int(v) for k, v in metricas.items()} if metricas else {}


def limpiar_cache():
    claves = redis_client.keys("consulta_ecommerce:*")
    if claves:
        redis_client.delete(*claves)
    redis_client.delete("historial_consultas")
    redis_client.delete("metricas")


# =========================
# Interfaz principal
# =========================
st.title("🛒 Asistente inteligente de pedidos ecommerce")
st.write(
    "Aplicación con **Streamlit + Redis + IA simulada** para responder consultas frecuentes "
    "sobre pedidos, devoluciones, pagos, cancelaciones y reclamos."
)

with st.sidebar:
    st.header("⚙️ Panel del sistema")
    st.write("**Tecnologías:**")
    st.write("- Streamlit")
    st.write("- Redis")
    st.write("- Docker Compose")
    st.write("- IA simulada")

    st.divider()
    st.write("**Pedidos de prueba:**")
    for codigo in PEDIDOS.keys():
        st.code(codigo)

    st.divider()
    if st.button("🧹 Limpiar caché e historial"):
        limpiar_cache()
        st.success("Caché e historial limpiados correctamente.")
        st.rerun()

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Consulta del cliente")

    numero_pedido = st.text_input(
        "Número de pedido",
        value="PED-45821",
        placeholder="Ejemplo: PED-45821"
    )

    pregunta = st.text_area(
        "Pregunta del cliente",
        placeholder="Ejemplo: ¿Dónde está mi pedido y cuándo llegará?",
        height=120
    )

    consultar = st.button("Consultar pedido", type="primary")

    if consultar:
        if not pregunta.strip():
            st.warning("Escribe una pregunta para continuar.")
        elif not numero_pedido.strip():
            st.warning("Escribe un número de pedido.")
        else:
            clave_cache = crear_clave_cache(pregunta, numero_pedido)
            respuesta_cache = redis_client.get(clave_cache)

            if respuesta_cache:
                categoria = detectar_categoria(pregunta)
                origen = "Redis caché"
                st.success("Respuesta obtenida desde Redis caché")
                st.markdown(respuesta_cache)
                guardar_historial(pregunta, numero_pedido, respuesta_cache, categoria, origen)
            else:
                respuesta, categoria = generar_respuesta_ia_simulada(pregunta, numero_pedido)
                origen = "IA simulada"

                redis_client.setex(clave_cache, CACHE_TTL_SECONDS, respuesta)
                st.info("Respuesta generada por IA simulada y guardada en Redis")
                st.markdown(respuesta)
                guardar_historial(pregunta, numero_pedido, respuesta, categoria, origen)

with col2:
    st.subheader("Datos del pedido")
    pedido_actual = PEDIDOS.get(numero_pedido.upper().strip())

    if pedido_actual:
        st.metric("Estado", pedido_actual["estado"])
        st.write(f"**Cliente:** {pedido_actual['cliente']}")
        st.write(f"**Producto:** {pedido_actual['producto']}")
        st.write(f"**Fecha estimada:** {pedido_actual['fecha_estimada']}")
        st.write(f"**Total:** {pedido_actual['total']}")
    else:
        st.warning("Pedido no encontrado en la data simulada.")

st.divider()

# =========================
# Métricas
# =========================
st.subheader("📊 Métricas de uso")
metricas = obtener_metricas()

m1, m2, m3 = st.columns(3)
m1.metric("Total consultas", metricas.get("total_consultas", 0))
m2.metric("Respuestas desde IA", metricas.get("origen:IA simulada", 0))
m3.metric("Respuestas desde Redis", metricas.get("origen:Redis caché", 0))

categorias = {
    "seguimiento": metricas.get("categoria:seguimiento", 0),
    "devoluciones": metricas.get("categoria:devoluciones", 0),
    "cancelacion": metricas.get("categoria:cancelacion", 0),
    "pagos": metricas.get("categoria:pagos", 0),
    "reclamos": metricas.get("categoria:reclamos", 0),
    "general": metricas.get("categoria:general", 0),
}

df_categorias = pd.DataFrame(
    list(categorias.items()),
    columns=["Categoría", "Cantidad"]
)
st.bar_chart(df_categorias.set_index("Categoría"))

# =========================
# Historial
# =========================
st.subheader("🕘 Historial reciente")
historial = redis_client.lrange("historial_consultas", 0, 9)

if historial:
    for item in historial:
        st.code(item)
else:
    st.write("Todavía no hay consultas registradas.")

st.divider()
st.caption(
    "Nota: Esta app usa IA simulada para fines académicos. Redis permite almacenar respuestas frecuentes en caché "
    "y responder más rápido cuando se repiten las consultas."
)