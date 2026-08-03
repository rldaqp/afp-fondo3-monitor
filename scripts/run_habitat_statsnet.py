"""Ejecuta el visor Hábitat usando el visor estadístico vigente de la SBS."""

import build_habitat_monitor as monitor

monitor.SBS_INDEX = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)

if __name__ == "__main__":
    monitor.main()
