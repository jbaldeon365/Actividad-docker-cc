import hashlib
import json
import os
import re
from datetime import datetime

import pandas as pd
import redis
import streamlit as st
from pymongo import MongoClient


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
MONGO_HOST = os.getenv("MONGO_HOST", "mongodb")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB = os.getenv("MONGO_DB", "ecommerce_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "pedidos")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 horas

st.set_page_config(
    page_title="Asistente Ecommerce con MongoDB y Redis",
    page_icon="🛒",
    layout="wide"
)


# ============================================================
# CONEXIONES
# ============================================================
@st.cache_resource
def conectar_mongodb():
    cliente = MongoClient(f"mongodb://{MONGO_HOST}:{MONGO_PORT}/")
    db = cliente[MONGO_DB]
    coleccion = db[MONGO_COLLECTION]
    return coleccion


@st.cache_resource
def conectar_redis():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True
    )


pedidos_collection = conectar_mongodb()
redis_client = conectar_redis()


# ============================================================
# DATA INICIAL PARA MONGODB
# ============================================================
PEDIDOS_INICIALES = [
    {
        "codigo": "PED-45821",
        "cliente": "Ana Torres",
        "estado": "En camino",
        "fecha_compra": "2026-05-17",
        "fecha_estimada": "2026-05-22",
        "transportista": "Urbano Express",
        "producto": "Laptop Lenovo IdeaPad 3",
        "total": "S/ 2,499.00"
    },
    {
        "codigo": "PED-78452",
        "cliente": "Luis Ramírez",
        "estado": "Preparando pedido",
        "fecha_compra": "2026-05-19",
        "fecha_estimada": "2026-05-24",
        "transportista": "Pendiente de asignación",
        "producto": "Audífonos Bluetooth JBL",
        "total": "S/ 189.90"
    },
    {
        "codigo": "PED-99310",
        "cliente": "María López",
        "estado": "Entregado",
        "fecha_compra": "2026-05-12",
        "fecha_estimada": "2026-05-16",
        "transportista": "Olva Courier",
        "producto": "Smart TV Samsung 55 pulgadas",
        "total": "S/ 1,899.00"
    },
    {
        "codigo": "PED-11220",
        "cliente": "Carlos Medina",
        "estado": "Retrasado",
        "fecha_compra": "2026-05-15",
        "fecha_estimada": "2026-05-21",
        "transportista": "Urbano Express",
        "producto": "Silla gamer ergonómica",
        "total": "S/ 699.00"
    }
]


def inicializar_pedidos():
    """Inserta pedidos de prueba solo si la colección está vacía."""
    if pedidos_collection.count_documents({}) == 0:
        pedidos_collection.insert_many(PEDIDOS_INICIALES)


inicializar_pedidos()


# ============================================================
# FUNCIONES DE MONGODB
# ============================================================
def obtener_pedido(codigo: str):
    codigo = codigo.upper().strip()
    pedido = pedidos_collection.find_one({"codigo": codigo}, {"_id": 0})
    return pedido


def listar_pedidos():
    pedidos = list(pedidos_collection.find({}, {"_id": 0}))
    return pedidos


def insertar_pedido(data: dict):
    codigo = data["codigo"].upper().strip()

    existente = pedidos_collection.find_one({"codigo": codigo})
    if existente:
        return False, "Ya existe un pedido con ese código."

    data["codigo"] = codigo
    pedidos_collection.insert_one(data)
    return True, "Pedido registrado correctamente en MongoDB."


def actualizar_estado_pedido(codigo: str, nuevo_estado: str, nueva_fecha_estimada: str, transportista: str):
    codigo = codigo.upper().strip()

    resultado = pedidos_collection.update_one(
        {"codigo": codigo},
        {
            "$set": {
                "estado": nuevo_estado,
                "fecha_estimada": nueva_fecha_estimada,
                "transportista": transportista
            }
        }
    )

    # Al actualizar el pedido, se limpia caché relacionada para evitar respuestas antiguas.
    limpiar_cache_por_pedido(codigo)

    return resultado.modified_count > 0


def eliminar_pedido(codigo: str):
    codigo = codigo.upper().strip()
    resultado = pedidos_collection.delete_one({"codigo": codigo})

    # Al eliminar pedido, se limpia caché relacionada.
    limpiar_cache_por_pedido(codigo)

    return resultado.deleted_count > 0


# ============================================================
# FUNCIONES DE REDIS
# ============================================================
def normalizar_texto(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def crear_clave_cache(pregunta: str, numero_pedido: str) -> str:
    texto_base = f"{normalizar_texto(pregunta)}|{numero_pedido.upper().strip()}"
    hash_texto = hashlib.md5(texto_base.encode()).hexdigest()
    return f"consulta_ecommerce:{numero_pedido.upper().strip()}:{hash_texto}"


def limpiar_cache_por_pedido(codigo: str):
    codigo = codigo.upper().strip()
    claves = redis_client.keys(f"consulta_ecommerce:{codigo}:*")
    if claves:
        redis_client.delete(*claves)


def limpiar_redis():
    claves_cache = redis_client.keys("consulta_ecommerce:*")
    if claves_cache:
        redis_client.delete(*claves_cache)

    redis_client.delete("historial_consultas")
    redis_client.delete("metricas")


# ============================================================
# MOTOR DE IA SIMULADA
# ============================================================
def detectar_categoria(pregunta: str) -> str:
    p = normalizar_texto(pregunta)

    if any(palabra in p for palabra in ["estado", "seguimiento", "donde", "dónde", "ubicacion", "ubicación", "llega", "tracking", "camino"]):
        return "seguimiento"

    if any(palabra in p for palabra in ["devolver", "devolucion", "devolución", "cambio", "cambiar", "reembolso"]):
        return "devoluciones"

    if any(palabra in p for palabra in ["cancelar", "anular", "cancelacion", "cancelación"]):
        return "cancelacion"

    if any(palabra in p for palabra in ["pago", "tarjeta", "yape", "plin", "efectivo", "boleta", "factura", "pagué", "pague"]):
        return "pagos"

    if any(palabra in p for palabra in ["dañado", "danado", "roto", "defectuoso", "garantia", "garantía", "reclamo", "incompleto"]):
        return "reclamos"

    return "general"


def generar_respuesta_ia_simulada(pregunta: str, pedido: dict) -> tuple[str, str]:
    """
    Esta función simula un motor de IA.
    No inventa los datos del pedido: usa la información recuperada desde MongoDB.
    """
    categoria = detectar_categoria(pregunta)

    if not pedido:
        respuesta = (
            "No encontré información para ese número de pedido en MongoDB. "
            "Verifica que el código esté escrito correctamente o registra el pedido desde el panel de administración."
        )
        return respuesta, categoria

    codigo = pedido["codigo"]

    if categoria == "seguimiento":
        respuesta = (
            f"Hola {pedido['cliente']}. Tu pedido {codigo} se encuentra en estado: **{pedido['estado']}**.\n\n"
            f"Producto: {pedido['producto']}\n\n"
            f"Fecha de compra: {pedido['fecha_compra']}\n\n"
            f"Fecha estimada de entrega: {pedido['fecha_estimada']}\n\n"
            f"Transportista: {pedido['transportista']}\n\n"
            "Te recomendamos revisar nuevamente más tarde, ya que el estado puede actualizarse durante el día."
        )

    elif categoria == "devoluciones":
        respuesta = (
            f"Hola {pedido['cliente']}. Para solicitar un cambio o devolución del pedido {codigo}, "
            "debes ingresar a la sección **Mis pedidos**, seleccionar la compra y registrar la solicitud. "
            "El producto debe conservar sus accesorios, empaque y comprobante de compra. "
            "El caso será evaluado según las políticas de devolución del ecommerce."
        )

    elif categoria == "cancelacion":
        if pedido["estado"] in ["Entregado", "En camino"]:
            respuesta = (
                f"Hola {pedido['cliente']}. El pedido {codigo} está en estado **{pedido['estado']}**, "
                "por lo que puede que ya no sea posible cancelarlo directamente. "
                "Puedes comunicarte con atención al cliente para evaluar una devolución o rechazo de entrega."
            )
        else:
            respuesta = (
                f"Hola {pedido['cliente']}. El pedido {codigo} todavía está en estado **{pedido['estado']}**. "
                "Puedes solicitar la cancelación desde **Mis pedidos** antes de que pase a despacho."
            )

    elif categoria == "pagos":
        respuesta = (
            f"Hola {pedido['cliente']}. El pedido {codigo} registra un total de **{pedido['total']}**. "
            "Para revisar el comprobante, ingresa a **Mis pedidos** y selecciona la opción de boleta o factura. "
            "Los métodos de pago dependen de las opciones habilitadas por la tienda."
        )

    elif categoria == "reclamos":
        respuesta = (
            f"Hola {pedido['cliente']}. Si el producto del pedido {codigo} llegó dañado, defectuoso o incompleto, "
            "registra un reclamo desde **Mis pedidos**. Adjunta fotos del producto, empaque y comprobante de compra "
            "para acelerar la evaluación del caso."
        )

    else:
        respuesta = (
            f"Hola {pedido['cliente']}. Puedo ayudarte con el pedido {codigo}. "
            "Este asistente responde consultas sobre seguimiento, pagos, cancelaciones, devoluciones y reclamos."
        )

    return respuesta, categoria


# ============================================================
# HISTORIAL Y MÉTRICAS
# ============================================================
def guardar_historial(pregunta: str, numero_pedido: str, respuesta: str, categoria: str, origen: str):
    registro = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pedido": numero_pedido.upper().strip(),
        "categoria": categoria,
        "origen": origen,
        "pregunta": pregunta,
        "respuesta": respuesta.replace("\n", " ")
    }

    redis_client.lpush("historial_consultas", json.dumps(registro, ensure_ascii=False))
    redis_client.ltrim("historial_consultas", 0, 49)

    redis_client.hincrby("metricas", "total_consultas", 1)
    redis_client.hincrby("metricas", f"categoria:{categoria}", 1)
    redis_client.hincrby("metricas", f"origen:{origen}", 1)


def obtener_metricas():
    metricas = redis_client.hgetall("metricas")
    return {k: int(v) for k, v in metricas.items()} if metricas else {}


def obtener_historial():
    historial = redis_client.lrange("historial_consultas", 0, 20)
    registros = []

    for item in historial:
        try:
            registros.append(json.loads(item))
        except json.JSONDecodeError:
            pass

    return registros


# ============================================================
# INTERFAZ
# ============================================================
st.title("🛒 Asistente inteligente de pedidos ecommerce")
st.write(
    "Aplicación con **Streamlit + MongoDB + Redis + IA simulada**. "
    "MongoDB almacena los pedidos, Redis guarda respuestas frecuentes en caché y el motor inteligente genera respuestas según la consulta del cliente."
)

with st.sidebar:
    st.header("⚙️ Panel del sistema")

    st.write("**Servicios Docker Compose:**")
    st.write("- Streamlit: interfaz web")
    st.write("- MongoDB: base de datos de pedidos")
    st.write("- Mongo Express: visor de MongoDB")
    st.write("- Redis: caché de respuestas")
    st.write("- Redis Commander: visor de Redis")

    st.divider()

    if st.button("🧹 Limpiar Redis caché e historial"):
        limpiar_redis()
        st.success("Redis limpiado correctamente.")
        st.rerun()

tab_consulta, tab_pedidos, tab_admin, tab_metricas = st.tabs(
    ["💬 Consultar pedido", "📦 Pedidos en MongoDB", "➕ Administrar pedidos", "📊 Métricas e historial"]
)


# ============================================================
# TAB 1: CONSULTAR PEDIDO
# ============================================================
with tab_consulta:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Consulta del cliente")

        pedidos_disponibles = listar_pedidos()
        codigos_pedidos = [p["codigo"] for p in pedidos_disponibles]

        numero_pedido = st.selectbox(
            "Número de pedido",
            options=codigos_pedidos if codigos_pedidos else ["PED-00000"]
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
            else:
                pedido = obtener_pedido(numero_pedido)
                clave_cache = crear_clave_cache(pregunta, numero_pedido)
                respuesta_cache = redis_client.get(clave_cache)

                if respuesta_cache:
                    categoria = detectar_categoria(pregunta)
                    origen = "Redis caché"
                    st.success("Respuesta obtenida desde Redis caché")
                    st.markdown(respuesta_cache)
                    guardar_historial(pregunta, numero_pedido, respuesta_cache, categoria, origen)
                else:
                    respuesta, categoria = generar_respuesta_ia_simulada(pregunta, pedido)
                    origen = "IA simulada"

                    redis_client.setex(clave_cache, CACHE_TTL_SECONDS, respuesta)
                    st.info("Respuesta generada por IA simulada usando datos de MongoDB y guardada en Redis")
                    st.markdown(respuesta)
                    guardar_historial(pregunta, numero_pedido, respuesta, categoria, origen)

    with col2:
        st.subheader("Datos desde MongoDB")
        pedido_actual = obtener_pedido(numero_pedido)

        if pedido_actual:
            st.metric("Estado", pedido_actual["estado"])
            st.write(f"**Cliente:** {pedido_actual['cliente']}")
            st.write(f"**Producto:** {pedido_actual['producto']}")
            st.write(f"**Fecha compra:** {pedido_actual['fecha_compra']}")
            st.write(f"**Fecha estimada:** {pedido_actual['fecha_estimada']}")
            st.write(f"**Transportista:** {pedido_actual['transportista']}")
            st.write(f"**Total:** {pedido_actual['total']}")
        else:
            st.warning("Pedido no encontrado en MongoDB.")


# ============================================================
# TAB 2: LISTAR PEDIDOS
# ============================================================
with tab_pedidos:
    st.subheader("Pedidos almacenados en MongoDB")

    pedidos = listar_pedidos()

    if pedidos:
        df_pedidos = pd.DataFrame(pedidos)
        columnas = ["codigo", "cliente", "producto", "estado", "fecha_compra", "fecha_estimada", "transportista", "total"]
        df_pedidos = df_pedidos[columnas]
        st.dataframe(df_pedidos, use_container_width=True, hide_index=True)
    else:
        st.info("No hay pedidos registrados.")


# ============================================================
# TAB 3: ADMINISTRAR PEDIDOS
# ============================================================
with tab_admin:
    st.subheader("Registrar nuevo pedido en MongoDB")

    with st.form("form_nuevo_pedido"):
        c1, c2 = st.columns(2)

        with c1:
            nuevo_codigo = st.text_input("Código de pedido", placeholder="Ejemplo: PED-55555")
            nuevo_cliente = st.text_input("Cliente", placeholder="Ejemplo: José Baldeón")
            nuevo_producto = st.text_input("Producto", placeholder="Ejemplo: Mouse gamer Logitech")
            nuevo_total = st.text_input("Total", placeholder="Ejemplo: S/ 129.90")

        with c2:
            nuevo_estado = st.selectbox(
                "Estado",
                ["Preparando pedido", "En camino", "Entregado", "Retrasado", "Cancelado"]
            )
            nueva_fecha_compra = st.date_input("Fecha de compra")
            nueva_fecha_estimada = st.date_input("Fecha estimada")
            nuevo_transportista = st.text_input("Transportista", placeholder="Ejemplo: Olva Courier")

        guardar = st.form_submit_button("Guardar pedido")

        if guardar:
            if not nuevo_codigo or not nuevo_cliente or not nuevo_producto:
                st.warning("Completa como mínimo código, cliente y producto.")
            else:
                data = {
                    "codigo": nuevo_codigo,
                    "cliente": nuevo_cliente,
                    "estado": nuevo_estado,
                    "fecha_compra": str(nueva_fecha_compra),
                    "fecha_estimada": str(nueva_fecha_estimada),
                    "transportista": nuevo_transportista if nuevo_transportista else "Pendiente de asignación",
                    "producto": nuevo_producto,
                    "total": nuevo_total if nuevo_total else "S/ 0.00"
                }

                ok, mensaje = insertar_pedido(data)

                if ok:
                    st.success(mensaje)
                    st.rerun()
                else:
                    st.error(mensaje)

    st.divider()

    st.subheader("Actualizar estado de pedido")

    pedidos_actuales = listar_pedidos()
    codigos_actuales = [p["codigo"] for p in pedidos_actuales]

    if codigos_actuales:
        with st.form("form_actualizar_pedido"):
            codigo_update = st.selectbox("Pedido a actualizar", codigos_actuales, key="codigo_update")
            estado_update = st.selectbox(
                "Nuevo estado",
                ["Preparando pedido", "En camino", "Entregado", "Retrasado", "Cancelado"],
                key="estado_update"
            )
            fecha_update = st.date_input("Nueva fecha estimada", key="fecha_update")
            transportista_update = st.text_input("Transportista", value="Urbano Express", key="transportista_update")

            actualizar = st.form_submit_button("Actualizar pedido")

            if actualizar:
                ok = actualizar_estado_pedido(
                    codigo_update,
                    estado_update,
                    str(fecha_update),
                    transportista_update
                )

                if ok:
                    st.success("Pedido actualizado correctamente. También se limpió su caché en Redis.")
                    st.rerun()
                else:
                    st.warning("No se modificó el pedido. Puede que los datos sean iguales.")

        st.divider()

        st.subheader("Eliminar pedido")

        codigo_delete = st.selectbox("Pedido a eliminar", codigos_actuales, key="codigo_delete")

        if st.button("Eliminar pedido"):
            ok = eliminar_pedido(codigo_delete)

            if ok:
                st.success("Pedido eliminado correctamente de MongoDB.")
                st.rerun()
            else:
                st.error("No se pudo eliminar el pedido.")
    else:
        st.info("No hay pedidos para actualizar o eliminar.")


# ============================================================
# TAB 4: MÉTRICAS E HISTORIAL
# ============================================================
with tab_metricas:
    st.subheader("Métricas de uso")

    metricas = obtener_metricas()

    m1, m2, m3 = st.columns(3)
    m1.metric("Total consultas", metricas.get("total_consultas", 0))
    m2.metric("Respuestas desde IA simulada", metricas.get("origen:IA simulada", 0))
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

    st.divider()

    st.subheader("Historial reciente desde Redis")

    registros = obtener_historial()

    if registros:
        df_historial = pd.DataFrame(registros)
        columnas = ["fecha", "pedido", "categoria", "origen", "pregunta", "respuesta"]
        df_historial = df_historial[columnas]
        st.dataframe(df_historial, use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay consultas registradas.")


st.caption(
    "MongoDB almacena los pedidos. Redis almacena respuestas frecuentes en caché. "
    "La IA simulada interpreta la intención del cliente y genera la respuesta usando los datos del pedido."
)
