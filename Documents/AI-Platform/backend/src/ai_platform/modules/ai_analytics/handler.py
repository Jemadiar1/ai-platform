"""
Handler para el módulo ai-analytics.

Generación de reportes, análisis de métricas y forecasts.

Acciones disponibles:
- generate_report: Generar reporte completo de analytics
- analyze_metrics: Analizar métricas específicas para insights
- forecast_trends: Predecir tendencias basadas en datos históricos
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.core.config import get_settings
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-analytics."""
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de analytics solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action", "default")
        
        actions = {
            "generate_report": self.generate_report,
            "analyze_metrics": self.analyze_metrics,
            "forecast_trends": self.forecast_trends,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-analytics: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-analytics: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-analytics")
        try:
            result = actions[action](payload)
            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "action": action,
                    "status": "error",
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            logger.info(f"{action} completado")
            return {
                "action": action,
                "status": "success",
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error ejecutando {action} en ai-analytics: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def generate_report(self, payload: dict) -> dict:
        """
        Generar reporte completo de analytics.
        
        Parámetros:
            payload: {
                "report_type": "monthly",
                "date_range": {"start": "2026-04-01", "end": "2026-04-30"},
                "modules": ["ai-social", "ai-ads", "ai-connect"],
                "metrics": ["engagement", "conversions", "revenue"]
            }
        
        Retorna:
            {"report": {...}, "summary": "...", "executive_summary": "..."}
        """
        report_type = scanner.sanitize(payload.get("report_type", "monthly"))
        date_range = payload.get("date_range", {})
        modules = payload.get("modules", [])
        metrics = payload.get("metrics", [])
        tenant_id = payload.get("tenant_id")
        
        start_date = scanner.sanitize(date_range.get("start", "") if isinstance(date_range.get("start"), str) else "")
        end_date = scanner.sanitize(date_range.get("end", "") if isinstance(date_range.get("end"), str) else "")
        
        logger.info(f"Generando reporte {report_type} ({start_date} - {end_date})")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60.0
            )
            
            # Incluir datos del payload como contexto
            data_context = ""
            if "custom_data" in payload:
                custom_data_text = json.dumps(payload["custom_data"], indent=2, ensure_ascii=False)
                data_context = f"\n\nDatos adicionales:\n{scanner.sanitize(custom_data_text)}"
            
            system_prompt = (
                f"Eres un analista de datos experto.\n"
                f"Generar reporte: {report_type}\n"
                f"Período: {start_date} → {end_date}\n"
                f"Módulos: {', '.join(modules) if modules else 'todos'}\n"
                f"Métricas: {', '.join(metrics) if metrics else 'todas relevantes'}\n\n"
                f"El reporte debe incluir:\n"
                f"1. Resumen ejecutivo (2-3 párrafos)\n"
                f"2. Métricas clave con variación vs período anterior\n"
                f"3. Análisis por módulo\n"
                f"4. Top logros y alertas\n"
                f"5. Recomendaciones accionables\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                '{"executive_summary": "...", "key_metrics": {{"engagement": 0, "conversion_rate": 0, ...}}, '
                '"module_breakdown": {{"{module}": {{"metrics": {{}}, "notes": "..."}}}}, '
                '"top_achievements": [], "alerts": [], "recommendations": [], '
                '"data_quality_notes": "..."}'
            )
            
            user_prompt = (
                f"Generar reporte {report_type} del {start_date} al {end_date}.\n"
                f"Módulos: {', '.join(modules) if modules else 'todos los módulos disponibles'}\n"
                f"Métricas de interés: {', '.join(metrics) if metrics else 'todas las métricas relevantes'}"
            )
            if data_context:
                user_prompt += data_context
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en generate_report: {e}")
                    result = {"executive_summary": "Error de parseo JSON", "key_metrics": {}, "module_breakdown": {}, "top_achievements": [], "alerts": [], "recommendations": [], "data_quality_notes": ""}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info("Reporte generado exitosamente")
            
            return {
                "report_type": report_type,
                "date_range": date_range,
                "modules_included": modules,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **result
            }
        
        except Exception as e:
            logger.error(f"Error generando reporte: {e}")
            return {
                "report_type": report_type,
                "date_range": date_range,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "executive_summary": "Error generando reporte: " + str(e),
                "key_metrics": {},
                "module_breakdown": {},
                "top_achievements": [],
                "alerts": [],
                "recommendations": [],
                "error": str(e)
            }
    
    def analyze_metrics(self, payload: dict) -> dict:
        """
        Analizar métricas específicas para insights Profundos.
        
        Parámetros:
            payload: {
                "metrics": {
                    "daily_active_users": [100, 120, 135, 150],
                    "conversion_rate": [0.05, 0.06, 0.055, 0.07],
                    "churn_rate": [0.02, 0.018, 0.015, 0.012]
                },
                "period": "last_4_weeks",
                "focus": ["engagement", "retention"]
            }
        
        Retorna:
            {"insights": [...], "anomalies": [...], "trends": {...}, "action_items": [...]}
        """
        metrics_data = payload.get("metrics", {})
        period = scanner.sanitize(payload.get("period", "last_30_days"))
        focus_areas = payload.get("focus", [])
        
        logger.info(f"Analizando métricas: {list(metrics_data.keys())}")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            system_prompt = (
                "Eres un analista de datos senior especializado en SaaS.\n"
                "Analizar métricas y encontrar:\n"
                "- Tendencias (crecimiento, decrecimiento, tendencias estacionales)\n"
                "- Anomalías (valores atípicos que requieren atención)\n"
                "- Correlaciones entre métricas\n"
                "- Insights accionables\n\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"insights": [{"metric": "...", "finding": "...", "severity": "info|warning|critical", '
                '"action": "..."}], "anomalies": [{"metric": "...", "value": 0, "context": "..."}], '
                '"trend_analysis": {}, "correlations": [], "actionable_items": []}'
            )
            
            # Formatear métricas para el prompt
            metrics_text = "Métricas analizadas:\n"
            for metric_name, values in metrics_data.items():
                if isinstance(values, list):
                    last = values[-1] if values else 0
                    first = values[0] if values else 0
                    growth = ((last - first) / max(first, 1)) * 100
                    metrics_text += f"- {metric_name}: {', '.join(str(v) for v in values)} (tendencia: {growth:+.1f}%)\n"
                else:
                    metrics_text += f"- {metric_name}: {values}\n"
            
            if focus_areas:
                metrics_text += f"\nÁreas de enfoque: {', '.join(focus_areas)}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Período: {period}\n\n{metrics_text}"},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en analyze_metrics: {e}")
                    result = {"insights": [], "anomalies": [], "trend_analysis": {}, "correlations": [], "actionable_items": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info("Análisis de métricas completado")
            
            return {
                "period": period,
                "focus_areas": focus_areas,
                **result
            }
        
        except Exception as e:
            logger.error(f"Error analizando métricas: {e}")
            return {
                "period": period,
                "focus_areas": focus_areas,
                "insights": [],
                "anomalies": [],
                "trend_analysis": {},
                "correlations": [],
                "actionable_items": [],
                "error": str(e)
            }
    
    def forecast_trends(self, payload: dict) -> dict:
        """
        Predecir tendencias basadas en datos históricos.
        
        Parámetros:
            payload: {
                "metric": "monthly_revenue",
                "history": [5000, 5500, 6200, 7000, 7500, 8200],
                "periods": ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"],
                "forecast_months": 3
            }
        
        Retorna:
            {"forecast": [8900, 9500, 10200], "confidence": 0.85, "trend": "growing", ...}
        """
        metric_name = scanner.sanitize(payload.get("metric", ""))
        history = payload.get("history", [])
        periods = payload.get("periods", [])
        forecast_months = payload.get("forecast_months", 3)
        
        if not metric_name:
            raise ValueError("Se requiere 'metric' para forecast")
        if not history:
            raise ValueError("Se requiere 'history' con datos históricos")
        
        logger.info(f"Generando forecast de {forecast_months} meses para: {metric_name}")
        
        # Calcular estadísticas básicas del historial
        n = len(history)
        if n < 2:
            raise ValueError("Se necesitan al menos 2 puntos de datos históricos")
        
        growth_rates = []
        for i in range(1, n):
            if history[i-1] > 0:
                growth_rates.append((history[i] - history[i-1]) / history[i-1])
        
        avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0
        growth_std = (sum((r - avg_growth) ** 2 for r in growth_rates) / len(growth_rates)) ** 0.5 if len(growth_rates) > 0 else 0
        
        latest_value = history[-1]
        trend = "growing" if avg_growth > 0.02 else ("declining" if avg_growth < -0.02 else "stable")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            # Datos históricos con formato JSON-safe
            history_safe = []
            for v in history:
                try:
                    float(v)
                    history_safe.append(v)
                except (ValueError, TypeError):
                    history_safe.append(0)
            
            system_prompt = (
                "Eres un analista de datos experto en forecasting.\n"
                "Analizar tendencias históricas y predecir valores futuros.\n"
                "Considerar:\n"
                "- Tendencia lineal y curva\n"
                "- Estacionalidad (si detectable)\n"
                "- Volatilidad de los datos\n"
                "- Factores externos relevantes\n\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"forecast_values": [], "forecast_with_bounds": {"low": [], "mid": [], "high": []}, '
                '"confidence_scores": [], "trend_summary": "...", '
                '"volatility": 0, "seasonal_patterns": [], "risk_factors": [], "upside_opportunities": []}'
            )
            
            # Construir texto de datos históricos
            history_text = f"Métrica: {metric_name}\n"
            if periods and len(periods) == len(history_safe):
                for p, v in zip(periods, history_safe):
                    history_text += f"- {p}: {v}\n"
            else:
                history_text += f"\nDatos: {', '.join(str(v) for v in history_safe)}\n"
            
            history_text += f"\nPromedio de crecimiento: {avg_growth:.2%}\n"
            history_text += f"Tendencia actual: {trend}\n"
            history_text += f"Valor más reciente: {latest_value}\n"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": history_text},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en forecast_trends: {e}")
                    result = {"forecast_with_bounds": [], "forecast_values": [], "forecast_with_mid": [], "confidence_scores": [], "trend_summary": "", "volatility": 0, "seasonal_patterns": [], "risk_factors": [], "upside_opportunities": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            # Combinar forecast computacional con LLM insights
            llm_forecast = result.get("forecast_with_mid", result.get("forecast_values", []))
            
            # Calcular base forecast estadístico
            base_forecast = []
            for i in range(1, forecast_months + 1):
                forecast_val = latest_value * ((1 + avg_growth) ** i)
                uncertainty = forecast_val * growth_std * (i ** 0.5)
                base_forecast.append({
                    "low": round(max(0, forecast_val - uncertainty)),
                    "mid": round(forecast_val),
                    "high": round(forecast_val + uncertainty)
                })
            
            # Usar LLM forecast si disponible, sino usar base
            if base_forecast:
                result["forecast_with_bounds"] = base_forecast
            
            # Fix 7: Asegurar que result siempre está definido antes de retornar
            if not isinstance(result, dict):
                result = {}
            
            logger.info(f"Forecast generado: {metric_name} → {base_forecast[-1] if base_forecast else 'N/A'}")
            
            return {
                "metric": metric_name,
                "periods": periods[n-1:n-1+len(periods)] if periods else [],
                "forecast_months": forecast_months,
                "latest_value": latest_value,
                "avg_growth_rate": round(avg_growth, 4),
                "trend": trend,
                "base_forecast": base_forecast,
                **result
            }
        
        except Exception as e:
            logger.error(f"Error generando forecast: {e}")
            base_forecast = []
            for i in range(1, forecast_months + 1):
                forecast_val = latest_value * ((1 + avg_growth) ** i)
                uncertainty = forecast_val * growth_std * (i ** 0.5)
                base_forecast.append({
                    "low": round(max(0, forecast_val - uncertainty)),
                    "mid": round(forecast_val),
                    "high": round(forecast_val + uncertainty)
                })
            
            return {
                "metric": metric_name,
                "forecast_months": forecast_months,
                "latest_value": latest_value,
                "avg_growth_rate": round(avg_growth, 4),
                "trend": trend,
                "base_forecast": base_forecast,
                "forecast_with_bounds": base_forecast,
                "error": str(e)
            }
