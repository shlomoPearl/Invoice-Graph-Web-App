import io
import matplotlib
import plotly.graph_objs as go
from matplotlib import pyplot as plt
config = {"displayModeBar": False, "staticPlot": True}
matplotlib.use('Agg')


class GraphPlot:
    def __init__(self, bill_dict, title="Payment Graph"):
        self.config = config
        self.dates = list(bill_dict.keys())
        self.values = list(bill_dict.values())
        self.title = title

    def get_html_graph(self):
        dates = self.dates
        values = self.values
        fig = go.Figure(data=[go.Bar(x=dates, y=values, text=values, textposition='outside')])
        fig.update_layout(
            title=self.title,
            xaxis_title="Date",
            yaxis_title="Amount",
            template="plotly_white"
        )
        return fig.to_html(config=config)

    def download_by_f(self, format_d: str):
        dates = self.dates
        values = self.values
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(dates, values)
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height,
                    f'{height:.2f}',
                    ha='center', va='bottom')
        ax.set_title(self.title)
        ax.set_xlabel("Date")
        ax.set_ylabel("Amount")
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format=format_d, dpi=300, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf.getvalue()
