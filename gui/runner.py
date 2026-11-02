"""Executa algoritmos do TopoLab em segundo plano (tarefa do QGIS), sem travar a janela.

Uso: ``run(widget, "topolab:tin_contours", params, done, load=True)``. ``done(res)`` é chamado
na linha principal quando termina bem; ``res`` é o dicionário de resultados (com as camadas já
adicionadas ao projeto, como no ``processing.runAndLoadResults``). Erros vão para a barra de
mensagens do QGIS. Uma tarefa por vez: enquanto uma roda, os botões da janela ficam bloqueados
e a barra de status mostra o progresso e o botão "Cancelar".

Sem o gerenciador de tarefas (testes fora do QGIS), roda de forma síncrona.
"""
import processing
from qgis.core import QgsApplication, QgsProject

_current = {}          # tarefa em andamento: task, context, feedback, alg (precisam viver até o fim)


def busy():
    return bool(_current)


def _window(widget):
    w = widget.window() if widget is not None else None
    return w if hasattr(w, "task_started") else None


def _iface(widget):
    return getattr(widget, "iface", None)


def _error(widget, text):
    iface = _iface(widget)
    if iface is not None:
        iface.messageBar().pushCritical("TopoLab", text)


def _sync(widget, alg_id, params, done, load):
    try:
        res = (processing.runAndLoadResults if load else processing.run)(alg_id, params)
    except Exception as exc:  # noqa: BLE001
        _error(widget, str(exc))
        return
    done(res)


def run(widget, alg_id, params, done, load=True, label=None):
    """Roda o algoritmo em segundo plano e chama ``done(resultados)`` ao terminar bem."""
    try:
        from qgis.core import (
            QgsProcessingAlgRunnerTask, QgsProcessingContext, QgsProcessingFeedback,
            QgsProcessingOutputLayerDefinition, QgsProcessingParameterFeatureSink,
            QgsProcessingParameterRasterDestination, QgsProcessingParameterVectorDestination,
        )
        manager = QgsApplication.taskManager()
    except (ImportError, AttributeError):
        return _sync(widget, alg_id, params, done, load)
    if busy():
        iface = _iface(widget)
        if iface is not None:
            iface.messageBar().pushWarning("TopoLab", "Espere o cálculo em andamento terminar "
                                                      "(ou cancele-o na barra de status).")
        return
    alg = QgsApplication.processingRegistry().createAlgorithmById(alg_id)
    if alg is None:
        return _error(widget, f"Algoritmo {alg_id} não encontrado.")
    params = dict(params)
    if load:  # como o runAndLoadResults: as saídas temporárias entram no projeto ao terminar
        sinks = (QgsProcessingParameterFeatureSink, QgsProcessingParameterVectorDestination,
                 QgsProcessingParameterRasterDestination)
        for p in alg.destinationParameterDefinitions():
            if isinstance(p, sinks) and params.get(p.name()):
                v = params[p.name()]
                if isinstance(v, QgsProcessingOutputLayerDefinition):
                    v.destinationProject = QgsProject.instance()
                else:
                    params[p.name()] = QgsProcessingOutputLayerDefinition(v, QgsProject.instance())
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    feedback = QgsProcessingFeedback()
    task = QgsProcessingAlgRunnerTask(alg, params, context, feedback)
    title = label or alg.displayName()
    win = _window(widget)

    def finished(ok, results):
        canceled = feedback.isCanceled()
        loaded_error = None
        if ok and not canceled and load:
            try:
                from processing.gui.Postprocessing import handleAlgorithmResults
                handleAlgorithmResults(alg, context, feedback)
            except Exception as exc:  # noqa: BLE001
                loaded_error = str(exc)
        # libera antes do retorno: `done` pode disparar o próximo cálculo
        _current.clear()
        if win is not None:
            win.task_finished()
        if canceled:
            iface = _iface(widget)
            if iface is not None:
                iface.messageBar().pushInfo("TopoLab", f"{title}: cancelado.")
            return
        if not ok:
            log = feedback.textLog().strip().splitlines() if hasattr(feedback, "textLog") else []
            msg = next((l for l in reversed(log) if l.strip()), "") or "falha no cálculo"
            return _error(widget, f"{title}: {msg}")
        if loaded_error:
            return _error(widget, f"{title}: {loaded_error}")
        try:
            done(results)
        except Exception as exc:  # noqa: BLE001
            _error(widget, str(exc))

    task.executed.connect(finished)
    _current.update(task=task, context=context, feedback=feedback, alg=alg)
    if win is not None:
        win.task_started(title, feedback)
    manager.addTask(task)


def cancel():
    fb = _current.get("feedback")
    if fb is not None:
        fb.cancel()


def wait(timeout_s=600):
    """Espera a tarefa atual terminar, processando eventos (útil em testes e scripts)."""
    import time
    t0 = time.time()
    while busy() and time.time() - t0 < timeout_s:
        QgsApplication.processEvents()
        time.sleep(0.02)
    return not busy()
