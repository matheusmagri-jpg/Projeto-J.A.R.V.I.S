"""Desenha o ícone do Jarvis (anéis de HUD ciano e laranja com "J") e salva como .ico.

Uso: python -m nexo.interface.icone   -> gera nexo/interface/jarvis.ico
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CIANO = (61, 226, 255)
LARANJA = (255, 138, 43)
FUNDO = (3, 10, 18)
DESTINO = Path(__file__).with_name("jarvis.ico")


def _fonte(tamanho: int):
    for nome in ("bahnschrift.ttf", "segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def desenhar(lado: int = 512) -> Image.Image:
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = lado / 2
    # disco escuro de fundo
    d.ellipse([lado * .03, lado * .03, lado * .97, lado * .97], fill=FUNDO + (255,))

    # brilho ciano por baixo dos anéis
    brilho = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    ImageDraw.Draw(brilho).ellipse([lado * .14, lado * .14, lado * .86, lado * .86], outline=CIANO + (200,),
                                   width=int(lado * .05))
    img.alpha_composite(brilho.filter(ImageFilter.GaussianBlur(lado * .035)))
    d = ImageDraw.Draw(img)

    # anel externo com marcações
    r = lado * .44
    for i in range(60):
        a = i / 60 * 2 * math.pi
        r1 = r - (lado * .05 if i % 5 == 0 else lado * .025)
        d.line([(c + math.cos(a) * r1, c + math.sin(a) * r1), (c + math.cos(a) * r, c + math.sin(a) * r)],
               fill=CIANO + (255 if i % 5 == 0 else 150,), width=max(1, int(lado * (.012 if i % 5 == 0 else .006))))

    # arcos ciano e laranja (o "mostrador" do painel)
    caixa = lambda f: [c - lado * f, c - lado * f, c + lado * f, c + lado * f]
    d.arc(caixa(.36), 200, 340, fill=CIANO + (255,), width=int(lado * .045))
    d.arc(caixa(.36), 20, 120, fill=CIANO + (255,), width=int(lado * .045))
    d.arc(caixa(.30), 130, 190, fill=LARANJA + (255,), width=int(lado * .03))
    d.arc(caixa(.30), 300, 350, fill=LARANJA + (255,), width=int(lado * .03))
    d.ellipse(caixa(.25), outline=CIANO + (230,), width=max(2, int(lado * .012)))

    # "J" no centro
    fonte = _fonte(int(lado * .2))
    caixa_texto = d.textbbox((0, 0), "J", font=fonte)
    x = c - (caixa_texto[2] - caixa_texto[0]) / 2 - caixa_texto[0]
    y = c - (caixa_texto[3] - caixa_texto[1]) / 2 - caixa_texto[1]
    sombra = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).text((x, y), "J", font=fonte, fill=CIANO + (255,))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(lado * .02)))
    ImageDraw.Draw(img).text((x, y), "J", font=fonte, fill=(235, 252, 255, 255))
    return img


def gerar(destino: Path = DESTINO) -> Path:
    desenhar().save(destino, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return destino


if __name__ == "__main__":
    print(gerar())
