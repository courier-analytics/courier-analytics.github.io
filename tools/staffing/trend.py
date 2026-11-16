"""Publication charts for the observed weekly core (not a fixed cohort)."""
import io
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS={7745:'#23815d',8889:'#2964b5',9107:'#db792b'}


def figure(report, shop=None, compact=False):
    plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none'})
    shops=[shop] if shop else [int(s) for s in report['shops']]
    fig,axes=plt.subplots(1,3,figsize=(30.8,5.15) if compact else (32,16.2),dpi=100)
    fig.patch.set_facecolor('#f7f9fc')
    if not compact:
        fig.suptitle('Растёт ли ядро курьеров? '+ ' и '.join('ДС '+str(s) for s in shops),fontsize=33,fontweight='bold',x=.035,ha='left',y=.96)
        fig.text(.035,.86,'12 октября — 15 ноября 2026 · недели 910–914 · ядро: более 50 рабочих часов за склад-неделю',fontsize=20,color='#65748b')
    fields=[('Численность ядра, человек',lambda w:w['groups']['core']['staff'],False),
            ('Ядро в недельном штате, %',lambda w:w['core_staff_percent'],True),
            ('Ядро в фактических выходах, %',lambda w:w['core_shift_percent'],True)]
    for index,(axis,(title,value,percent)) in enumerate(zip(axes,fields)):
        axis.set_facecolor('#ffffff')
        max_y=0
        for identity in shops:
            weeks=report['shops'][str(identity)]['weeks'];values=[value(w) for w in weeks]
            max_y=max(max_y,max((v for v in values if v is not None),default=0))
            axis.plot(range(5),values,marker='o',markersize=9,linewidth=3,color=COLORS[identity],label=f'ДС {identity}',zorder=3)
            for x,y in enumerate(values):
                if y is None:continue
                # Keep labels apart where the comparison lines nearly meet.
                other=value(report['shops'][str(next(s for s in shops if s!=identity))]['weeks'][x]) if len(shops)>1 else None
                shift=(16 if other is None or y>=other else -24) if len(shops)>1 else 12
                label=str(int(y)) if not percent else f'{y:.1f}'.replace('.',',')+'%'
                axis.annotate(label,(x,y),xytext=(0,shift),textcoords='offset points',ha='center',fontsize=17 if compact else 19,color=COLORS[identity],fontweight='bold')
        if index==2:
            axis.axhline(70,color='#627365',linestyle='--',linewidth=2,zorder=1)
            axis.text(4.05,72,'Цель 70%',ha='right',fontsize=16,color='#627365')
        axis.set_ylim(0,100 if percent else math.ceil((max_y+6)/10)*10)
        axis.set_xlim(-.3,4.3);axis.set_xticks(range(5),[str(w) for w in range(910,915)])
        axis.tick_params(labelsize=16 if compact else 19)
        axis.set_title(title,fontsize=21 if compact else 24,pad=22,fontweight='bold',loc='left')
        axis.set_xlabel('Корпоративная неделя',fontsize=15 if compact else 18,labelpad=10)
        axis.grid(axis='y',alpha=.18,zorder=0)
        axis.spines[['top','right']].set_visible(False)
        axis.spines[['left','bottom']].set_color('#cbd3df')
    if compact:
        fig.subplots_adjust(left=.03,right=.98,top=.80,bottom=.16,wspace=.25)
    else:
        axes[0].legend(loc='upper right',fontsize=19,frameon=False)
        fig.subplots_adjust(left=.045,right=.97,top=.73,bottom=.27,wspace=.30)
        changes=[];last_changes=[]
        for identity in shops:
            counts=[w['groups']['core']['staff'] for w in report['shops'][str(identity)]['weeks']]
            pct=(counts[-1]/counts[0]-1)*100 if counts[0] else 0
            changes.append(f"ДС {identity}: {counts[0]} → {counts[-1]} ({pct:+.1f}%)".replace('.',','))
            last_changes.append(f"ДС {identity}: {counts[-1]-counts[-2]:+d} чел.")
        fig.text(.035,.135,'Изменение ядра за пять недель: '+'; '.join(changes)+'.',fontsize=23,fontweight='bold',color='#23324b')
        conclusion=' Устойчивого роста за весь период нет.' if all(report['shops'][str(s)]['weeks'][-1]['groups']['core']['staff']<report['shops'][str(s)]['weeks'][0]['groups']['core']['staff'] for s in shops) else ''
        fig.text(.035,.085,'Неделя 914 к неделе 913: '+'; '.join(last_changes)+'.'+conclusion,fontsize=22,color='#23324b')
        fig.text(.035,.035,'Данные и исключения — в audit.md. Состав ядра пересчитывается каждую неделю; это не анализ удержания одной фиксированной группы.',fontsize=17,color='#65748b')
    return fig


def svg_panel(report,shop):
    fig=figure(report,shop,compact=True);stream=io.StringIO();fig.savefig(stream,format='svg',facecolor=fig.get_facecolor());plt.close(fig)
    return stream.getvalue()


def write_comparison(report,directory,svg_only=False):
    directory=Path(directory);fig=figure(report)
    for ext in (('svg',) if svg_only else ('png','svg')):fig.savefig(directory/f'core-trend-910-914.{ext}',format=ext,facecolor=fig.get_facecolor())
    plt.close(fig)
