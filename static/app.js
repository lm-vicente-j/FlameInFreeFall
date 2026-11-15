let datosOriginales = [];
let graficoInstancia = null;
let filtroTexto = "";
let filtroCategoria = null;
let solicitudEstudios = null;
let solicitudArchivos = null;
let solicitudEvidencia = null;
let solicitudDetalle = null;
let contextoEvidencia = "";
const LIMITE = 20;

function elemento(tag, texto = "", clase = "") {
    const nodo = document.createElement(tag);
    nodo.textContent = texto;
    if (clase) nodo.className = clase;
    return nodo;
}
function boton(texto, accion) {
    const nodo = elemento("button", texto);
    nodo.type = "button";
    nodo.addEventListener("click", accion);
    return nodo;
}
function estado(id, texto, error = false) {
    const nodo = document.getElementById(id);
    nodo.textContent = texto;
    nodo.classList.toggle("error", error);
}
async function pedirDatos(ruta, signal) {
    const response = await fetch(ruta, { signal });
    const respuesta = await response.json();
    if (!response.ok) {
        const mensaje = response.status === 503 ? "Datos no disponibles" : "No se pudo completar la consulta";
        throw new Error(mensaje + " (HTTP " + response.status + "; " + (respuesta.error?.code || "error") + ").");
    }
    if (!("data" in respuesta) || !respuesta.meta) throw new Error("Respuesta de API incompatible.");
    return respuesta;
}
function mostrarPaginacion(id, meta, cargar) {
    const nodo = document.getElementById(id);
    nodo.replaceChildren();
    const anterior = boton("Anterior", () => cargar(Math.max(0, meta.offset - meta.limit)));
    const siguiente = boton("Siguiente", () => cargar(meta.offset + meta.limit));
    anterior.disabled = meta.offset === 0;
    siguiente.disabled = meta.offset + meta.limit >= meta.total;
    const inicio = meta.total ? meta.offset + 1 : 0;
    nodo.append(anterior, elemento("span", inicio + "–" + Math.min(meta.offset + meta.limit, meta.total) +
        " de " + meta.total), siguiente);
}
function revision(status) {
    return ({ approved: "Aprobada", pending: "Pendiente", rejected: "Rechazada",
        not_required: "No requerida" })[status] || "No indicada";
}
document.addEventListener("DOMContentLoaded", () => {
    configurarBuscador();
    cargarEstudios();
    cargarRuns();
    cargarInvestigacionesArchivos();
    cargarSalud();
    document.getElementById("btn-cerrar-modal").addEventListener("click", () => {
        solicitudEvidencia?.abort();
        document.getElementById("modal-evidence").close();
    });
    document.getElementById("btn-cerrar-estudio").addEventListener("click", () => {
        solicitudDetalle?.abort();
        document.getElementById("modal-study").close();
    });
    document.getElementById("selector-evidence").addEventListener("change", cargarEvidencia);
    document.getElementById("investigacion-archivos").addEventListener("change", () => cargarArchivos());
    document.getElementById("filtros-archivos").addEventListener("submit", event => {
        event.preventDefault();
        cargarArchivos();
    });
});
async function cargarSalud() {
    try {
        const { data } = await pedirDatos("/api/health");
        const cantidad = valor => valor === null ? "no disponible" : String(valor);
        estado("estado-sistema", "Estado: " + data.readiness + " · Snapshot: " + (data.snapshot_date || "no disponible") +
            " · Investigaciones: " + cantidad(data.investigation_count) +
            " · Filas fuente: " + cantidad(data.run_record_count) +
            " · Experimentos verificados: " + cantidad(data.verified_run_count));
    } catch (error) {
        estado("estado-sistema", error.message, true);
    }
}
function configurarBuscador() {
    const input = document.getElementById("buscador");
    const botonesFiltro = document.querySelectorAll(".btn-filtro");
    const btnLimpiar = document.getElementById("btn-limpiar");
    let temporizador;
    input.addEventListener("input", e => {
        clearTimeout(temporizador);
        solicitudEstudios?.abort();
        filtroTexto = e.target.value;
        temporizador = setTimeout(() => aplicarFiltros(filtroTexto, filtroCategoria), 300);
    });
    botonesFiltro.forEach(boton => {
        boton.addEventListener("click", () => {
            clearTimeout(temporizador);
            const cat = boton.getAttribute("data-categoria");
            filtroCategoria = filtroCategoria === cat ? null : cat;
            botonesFiltro.forEach(b => b.setAttribute("aria-pressed",
                String(b.getAttribute("data-categoria") === filtroCategoria)));
            aplicarFiltros(filtroTexto, filtroCategoria);
        });
    });
    btnLimpiar.addEventListener("click", () => {
        clearTimeout(temporizador);
        input.value = "";
        botonesFiltro.forEach(b => b.setAttribute("aria-pressed", "false"));
        aplicarFiltros("", null);
    });
}
function aplicarFiltros(texto, categoria) {
    filtroTexto = texto;
    filtroCategoria = categoria;
    return cargarEstudios();
}
async function cargarEstudios(offset = 0) {
    solicitudEstudios?.abort();
    solicitudEstudios = new AbortController();
    const { signal } = solicitudEstudios;
    estado("estado-estudios", "Cargando investigaciones…");
    document.getElementById("contenedor-tarjetas").replaceChildren();
    document.getElementById("paginacion-estudios").replaceChildren();
    const query = new URLSearchParams({ limit: LIMITE, offset, q: filtroTexto.trim() });
    if (filtroCategoria) query.set("safety_category", filtroCategoria);
    try {
        const respuesta = await pedirDatos("/api/studies?" + query, signal);
        if (signal.aborted) return;
        datosOriginales = respuesta.data;
        dibujarTarjetas(datosOriginales, respuesta.meta.matches || []);
        estado("estado-estudios", respuesta.meta.total + " investigaciones encontradas.");
        mostrarPaginacion("paginacion-estudios", respuesta.meta, cargarEstudios);
    } catch (error) {
        if (!signal.aborted) estado("estado-estudios", error.message, true);
    }
}
function dibujarTarjetas(estudios, coincidencias = []) {
    const contenedor = document.getElementById("contenedor-tarjetas");
    contenedor.replaceChildren();
    if (!estudios.length) {
        contenedor.append(elemento("p", "No se encontraron investigaciones. Prueba otras palabras o quita los filtros."));
        return;
    }
    estudios.forEach(estudio => {
        const tarjeta = elemento("article", "", "tarjeta");
        tarjeta.append(elemento("h3", estudio.title + (estudio.acronym ? " (" + estudio.acronym + ")" : "")),
            elemento("p", estudio.summary.text), elemento("span", estudio.accession, "tag"),
            elemento("p", "Revisión: " + revision(estudio.review?.status), "nota"));
        const coincidencia = coincidencias.find(item => item.accession === estudio.accession);
        if (coincidencia) {
            tarjeta.append(elemento("p", "Posición de relevancia: " + coincidencia.rank, "nota"));
            coincidencia.evidence.forEach(item => tarjeta.append(elemento("blockquote", item.excerpt)));
            if (!coincidencia.evidence.length) tarjeta.append(elemento("p", "Sin extracto coincidente disponible.", "nota"));
        }
        const acciones = elemento("div", "", "controles");
        acciones.append(boton("Ver detalle", () => abrirDetalleEstudio(estudio.accession)),
            boton("Ver citas del resumen", () => abrirModalEvidencia(estudio.accession, estudio.summary.evidence_ids,
                "Resumen preparado · " + estudio.accession)),
            boton("Ver archivos", () => {
                document.getElementById("investigacion-archivos").value = estudio.accession;
                cargarArchivos();
                document.getElementById("explorador-archivos").scrollIntoView({ behavior: "smooth" });
            }));
        tarjeta.append(acciones);
        contenedor.append(tarjeta);
    });
}
function parrafoCitado(contenedor, estudio, texto, ids, contexto) {
    contenedor.append(elemento("p", texto || "No disponible"));
    if (ids?.length) contenedor.append(boton("Ver evidencia", () => abrirModalEvidencia(estudio.accession, ids, contexto)));
}
async function abrirDetalleEstudio(accession) {
    solicitudDetalle?.abort();
    solicitudDetalle = new AbortController();
    const { signal } = solicitudDetalle;
    const modal = document.getElementById("modal-study");
    const contenedor = document.getElementById("detalle-estudio");
    document.getElementById("titulo-estudio").textContent = accession;
    contenedor.replaceChildren(elemento("p", "Cargando detalle…"));
    if (!modal.open) modal.showModal();
    try {
        const { data: estudio } = await pedirDatos("/api/studies/" + encodeURIComponent(accession), signal);
        if (signal.aborted) return;
        document.getElementById("titulo-estudio").textContent = estudio.title;
        contenedor.replaceChildren(elemento("p", estudio.accession + " · Versión de fuente: " +
            estudio.source_version + " · Revisión: " + revision(estudio.review?.status)));
        parrafoCitado(contenedor, estudio, estudio.summary.text, estudio.summary.evidence_ids, "Resumen preparado");
        const etiquetas = { fuels: "Combustibles", geometry: "Geometría", oxygen: "Oxígeno", pressure: "Presión",
            flow: "Flujo", gravity: "Gravedad", measurements: "Mediciones", hardware: "Hardware" };
        for (const [campo, valor] of Object.entries(estudio.comparison || {})) {
            contenedor.append(elemento("h3", etiquetas[campo] || campo));
            parrafoCitado(contenedor, estudio, valor?.text, valor?.evidence_ids, etiquetas[campo] || campo);
        }
        const tipos = { objective: "Objetivo", approach: "Enfoque", hypothesis: "Hipótesis",
            expected_impact: "Impacto esperado", potential_application: "Aplicación potencial",
            reported_observation: "Observación reportada" };
        contenedor.append(elemento("h3", "Afirmaciones de la ficha"));
        (estudio.claims || []).forEach(claim => {
            const tipo = tipos[claim.type] || claim.type;
            contenedor.append(elemento("h4", claim.id + " · " + tipo));
            parrafoCitado(contenedor, estudio, claim.text, claim.evidence_ids, tipo + " · " + claim.id);
        });
        contenedor.append(elemento("h3", "Limitaciones"));
        (estudio.limitations || []).forEach(item =>
            parrafoCitado(contenedor, estudio, item.text, item.evidence_ids, "Limitación"));
    } catch (error) {
        if (!signal.aborted) contenedor.replaceChildren(elemento("p", error.message, "error"));
    }
}
async function abrirModalEvidencia(idEstudio, ids = null, contexto = "Resumen preparado") {
    solicitudEvidencia?.abort();
    solicitudEvidencia = new AbortController();
    const { signal } = solicitudEvidencia;
    contextoEvidencia = contexto;
    const modal = document.getElementById("modal-evidence");
    const selector = document.getElementById("selector-evidence");
    selector.replaceChildren();
    document.getElementById("evidence-text").textContent = "Cargando evidencia…";
    document.getElementById("evidence-locator").textContent = "";
    document.getElementById("evidence-authors").textContent = "";
    document.getElementById("evidence-context").textContent = contexto + " · " + idEstudio;
    document.getElementById("evidence-source").hidden = true;
    if (!modal.open) modal.showModal();
    try {
        const { data: estudio } = await pedirDatos("/api/studies/" + encodeURIComponent(idEstudio), signal);
        if (signal.aborted) return;
        const referencias = ids === null ? estudio.summary.evidence_ids : ids;
        referencias.forEach((id, indice) => {
            const opcion = elemento("option", "Cita " + (indice + 1) + " · " + id);
            opcion.value = id;
            selector.append(opcion);
        });
        if (!referencias.length) {
            document.getElementById("evidence-text").textContent = "No hay evidencia disponible para este contenido.";
            return;
        }
        selector.value = referencias[0];
        await cargarEvidencia();
    } catch (error) {
        if (!signal.aborted) document.getElementById("evidence-text").textContent = error.message;
    }
}
function enlaceSeguro(nodo, direccion) {
    nodo.hidden = true;
    nodo.removeAttribute("href");
    if (!direccion) return;
    try {
        const url = new URL(direccion);
        if (!["https:", "http:"].includes(url.protocol)) return;
        nodo.href = url.href;
        nodo.hidden = false;
    } catch { /* Missing or unsupported source URLs remain unavailable. */ }
}
function localizador(locator) {
    if (!locator) return "Localizador no disponible";
    const partes = [locator.kind];
    if (locator.field) partes.push("Campo: " + locator.field);
    if (locator.filename) partes.push(locator.filename);
    if (locator.page !== undefined) partes.push("Página: " + locator.page);
    if (locator.row !== undefined) partes.push("Fila: " + locator.row);
    if (locator.sheet) partes.push("Hoja: " + locator.sheet);
    if (locator.columns?.length) partes.push("Columnas: " + locator.columns.join(", "));
    return partes.filter(Boolean).join(" · ");
}
async function cargarEvidencia() {
    solicitudEvidencia?.abort();
    solicitudEvidencia = new AbortController();
    const { signal } = solicitudEvidencia;
    const id = document.getElementById("selector-evidence").value;
    const texto = document.getElementById("evidence-text");
    texto.textContent = "Cargando cita…";
    document.getElementById("evidence-locator").textContent = "";
    document.getElementById("evidence-authors").textContent = "";
    document.getElementById("evidence-source").hidden = true;
    if (!id) return;
    try {
        const { data } = await pedirDatos("/api/evidence/" + encodeURIComponent(id), signal);
        if (signal.aborted) return;
        texto.textContent = data.excerpt;
        document.getElementById("evidence-context").textContent = contextoEvidencia + " · " + data.investigation;
        document.getElementById("evidence-locator").textContent = localizador(data.locator);
        document.getElementById("evidence-authors").textContent =
            "Autoría: consultar la fuente original; el registro de evidencia no incluye autores.";
        enlaceSeguro(document.getElementById("evidence-source"), data.source_url);
    } catch (error) {
        if (!signal.aborted) texto.textContent = error.message;
    }
}
function cantidadConocida(valor, unidad) {
    return valor?.method !== "unknown" && valor?.unit === unidad &&
        Number.isFinite(valor.min) && Number.isFinite(valor.max) && valor.min <= valor.max;
}
function formatearCantidad(valor, unidad) {
    if (!cantidadConocida(valor, unidad)) return "Desconocido";
    const numero = n => n.toLocaleString("es-MX", { maximumFractionDigits: 8 });
    const etiqueta = valor.min === valor.max ? numero(valor.min) : numero(valor.min) + "–" + numero(valor.max);
    return (valor.qualifier === "approximate" ? "≈ " : "") + etiqueta;
}
function puntosConocidos(runs) {
    return runs.filter(run => {
        const o2 = run.conditions?.o2_percent;
        const presion = run.conditions?.pressure_kpa;
        return cantidadConocida(o2, "percent") && cantidadConocida(presion, "kPa") &&
            o2.min === o2.max && presion.min === presion.max;
    }).map(run => ({ x: run.conditions.o2_percent.min, y: run.conditions.pressure_kpa.min, nombre: run.id }));
}
function dibujarGrafico(runs) {
    if (graficoInstancia) {
        graficoInstancia.destroy();
        graficoInstancia = null;
    }
    if (typeof Chart === "undefined") {
        estado("estado-grafico", "Gráfico no disponible. Los datos se mantienen en la tabla.", true);
        return;
    }
    const canvas = document.getElementById("graficoRuns");
    const puntosReales = puntosConocidos(runs);
    graficoInstancia = new Chart(canvas.getContext("2d"), {
        type: "scatter",
        data: { datasets: [
            { label: "Filas fuente (página actual)", data: puntosReales, backgroundColor: "#008b9c", pointRadius: 5 },
            { label: "Atmósferas de referencia", data: [
                { x: 21.0, y: 14.7 * 6.894757293, nombre: "14.7 psia · 21% O₂" },
                { x: 26.5, y: 10.2 * 6.894757293, nombre: "10.2 psia · 26.5% O₂" },
                { x: 34.0, y: 8.2 * 6.894757293, nombre: "8.2 psia · 34% O₂" }
            ], backgroundColor: "#ff5722", pointRadius: 8, pointStyle: "rectRot" }
        ] },
        options: { responsive: true, maintainAspectRatio: false,
            scales: { x: { title: { display: true, text: "Oxígeno (%)" }, beginAtZero: true },
                y: { title: { display: true, text: "Presión (kPa)" }, beginAtZero: true } },
            plugins: { tooltip: { callbacks: { label: context => context.raw.nombre } } }
        }
    });
    estado("estado-grafico", puntosReales.length + " puntos de " + runs.length +
        " registros visibles; se omiten del gráfico los intervalos y las condiciones desconocidas.");
}
async function cargarRuns(offset = 0) {
    estado("estado-runs", "Cargando registros…");
    document.getElementById("tabla-runs-body").replaceChildren();
    document.getElementById("paginacion-runs").replaceChildren();
    if (graficoInstancia) { graficoInstancia.destroy(); graficoInstancia = null; }
    estado("estado-grafico", "Cargando registros…");
    try {
        const respuesta = await pedirDatos("/api/runs?" + new URLSearchParams({ limit: LIMITE, offset }));
        dibujarGrafico(respuesta.data);
        llenarTablaRuns(respuesta.data);
        estado("estado-runs", respuesta.meta.total + " filas fuente. " +
            (respuesta.meta.provisional ? "La selección contiene valores pendientes de revisión." : ""));
        mostrarPaginacion("paginacion-runs", respuesta.meta, cargarRuns);
    } catch (error) {
        estado("estado-runs", error.message, true);
        estado("estado-grafico", "No se pudieron cargar los registros para el gráfico.", true);
    }
}
function llenarTablaRuns(runs) {
    const tbody = document.getElementById("tabla-runs-body");
    tbody.replaceChildren();
    if (!runs.length) {
        const tr = elemento("tr"), td = elemento("td", "No se encontraron registros.");
        td.colSpan = 7;
        tr.append(td);
        tbody.append(tr);
    }
    runs.forEach(run => {
        const o2 = run.conditions?.o2_percent, presion = run.conditions?.pressure_kpa;
        const method = [o2?.method || "unknown", presion?.method || "unknown"].join(" / ");
        const gravity = (run.outcomes || []).map(outcome =>
            outcome.type + ": " + (outcome.gravity === "normal" ? "1 g ground test" :
                outcome.gravity === "microgravity" ? "Microgravedad" : "Desconocida")).join("; ") || "Sin resultados";
        const tr = elemento("tr");
        [run.id, run.kind, formatearCantidad(o2, "percent"), formatearCantidad(presion, "kPa"),
            method, gravity, revision(run.review_status)].forEach(valor => tr.append(elemento("td", valor)));
        tbody.append(tr);
    });
}
async function cargarInvestigacionesArchivos() {
    const selector = document.getElementById("investigacion-archivos");
    estado("estado-archivos", "Cargando investigaciones del catálogo…");
    try {
        const estudios = [];
        let offset = 0, respuesta;
        do {
            respuesta = await pedirDatos("/api/studies?" + new URLSearchParams({ limit: 100, offset }));
            estudios.push(...respuesta.data);
            offset += 100;
        } while (offset < respuesta.meta.total);
        selector.replaceChildren();
        estudios.forEach(estudio => {
            const opcion = elemento("option", estudio.accession + " · " + (estudio.acronym || estudio.title));
            opcion.value = estudio.accession;
            selector.append(opcion);
        });
        if (estudios.length) {
            selector.value = estudios[0].accession;
            await cargarArchivos();
        } else estado("estado-archivos", "No hay investigaciones disponibles para consultar archivos.");
    } catch (error) {
        selector.replaceChildren(elemento("option", "Catálogo no disponible"));
        estado("estado-archivos", error.message, true);
    }
}
async function cargarArchivos(offset = 0) {
    solicitudArchivos?.abort();
    solicitudArchivos = new AbortController();
    const { signal } = solicitudArchivos;
    const accession = document.getElementById("investigacion-archivos").value;
    document.getElementById("tabla-archivos-body").replaceChildren();
    document.getElementById("paginacion-archivos").replaceChildren();
    if (!accession) { estado("estado-archivos", "Selecciona una investigación."); return; }
    const query = new URLSearchParams({ limit: LIMITE, offset });
    for (const [parametro, id] of [["filename", "nombre-archivo"], ["category", "categoria-archivo"],
        ["extension", "extension-archivo"]]) {
        const valor = document.getElementById(id).value.trim();
        if (valor) query.set(parametro, valor);
    }
    estado("estado-archivos", "Cargando archivos…");
    try {
        const respuesta = await pedirDatos("/api/studies/" + encodeURIComponent(accession) + "/files?" + query, signal);
        if (signal.aborted) return;
        llenarTablaArchivos(respuesta.data);
        estado("estado-archivos", accession + " · " + respuesta.meta.total + " archivos catalogados.");
        mostrarPaginacion("paginacion-archivos", respuesta.meta, cargarArchivos);
    } catch (error) {
        if (!signal.aborted) estado("estado-archivos", error.message, true);
    }
}
function llenarTablaArchivos(archivos) {
    const tbody = document.getElementById("tabla-archivos-body");
    tbody.replaceChildren();
    if (!archivos.length) {
        const tr = elemento("tr"), td = elemento("td", "No se encontraron archivos con estos filtros.");
        td.colSpan = 7;
        tr.append(td);
        tbody.append(tr);
    }
    archivos.forEach(archivo => {
        const mb = Number.isFinite(archivo.bytes) ? (archivo.bytes / (1024 * 1024)).toFixed(2) + " MB" : "Desconocido";
        const tr = elemento("tr"), nombre = elemento("td", archivo.filename + " · v" + archivo.version);
        nombre.title = archivo.key;
        tr.append(nombre);
        const acceso = ({ public: "Público", restricted: "Restringido", hidden: "Oculto" })[archivo.access] || "Desconocido";
        [archivo.category, archivo.extension || "Sin extensión", mb, acceso,
            archivo.download_sha256 ? "Bytes verificados; procesamiento no indicado" : "Sin hash de descarga"]
            .forEach(valor => tr.append(elemento("td", valor)));
        const fuente = elemento("td"), enlace = elemento("a", "Ver investigación en PSI");
        enlace.target = "_blank";
        enlace.rel = "noopener noreferrer";
        enlaceSeguro(enlace, "https://psi.nasa.gov/physci/repo/data/investigations/" + encodeURIComponent(archivo.accession));
        fuente.append(enlace);
        tr.append(fuente);
        tbody.append(tr);
    });
}
