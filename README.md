# TopoLab v0.16.0 (experimental)

Plugin de topografia para o QGIS, com **janela própria** (não é painel acoplável).
Funciona no QGIS 4 (Qt6) e no QGIS 3.28 ou mais novo (Qt5).

## Novidades da 0.16.0
- Platô com **bermas**: a cada "desnível entre bermas" metros de altura, o talude ganha um degrau plano com a largura informada, no corte e no aterro. Volumes, off-set e cota de equilíbrio consideram os degraus; as bordas de cada berma (externa e interna) saem na camada do off-set como linhas 3D na cota da berma (TIPO = Berma de corte / Berma de aterro), prontas para locação. Conferido contra a fórmula exata de um platô quadrado em terreno plano (diferença de 0,001%).

## Novidades da 0.15.0
- Curvas, volumes, platô, mapas temáticos e camadas de perfil/seções rodam **em segundo plano** (tarefa do QGIS): a janela e o mapa continuam respondendo, a barra de status mostra o progresso e há um botão **Cancelar**. Um cálculo por vez; os campos ficam bloqueados enquanto ele roda.
- TIN com linhas de quebra e limite **~40% mais rápido**: os trechos de linha que faltam na triangulação são divididos de uma vez, até virarem arestas de Gabriel (nenhum ponto dentro do círculo que tem o trecho como diâmetro), em vez de uma bisseção por rodada (4 triangulações em vez de 9 nos dados de teste).
- Os pontos inseridos no limite do MDT tiram a cota da triangulação que já tem os vértices das linhas de quebra: onde o limite cruza um talvegue, o fundo do vale não fica mais raso (no teste, erro de 0,66 m caiu para 0,1 m).

## Novidades da 0.14.0
- Mapas temáticos (declividade, faixas de elevação, inundação, corte e aterro) geram **um polígono por classe**, com furos, em vez de um por triângulo: de ~23 mil feições para menos de 10, e o QGIS deixa de travar ao gravar e desenhar o mapa. Os vértices dos recortes são calculados uma única vez por aresta, então os polígonos se encaixam sem frestas. A opção "Juntar os polígonos de cada classe" pode ser desmarcada para voltar ao modo por triângulo (útil na declividade, para ter a orientação de cada triângulo).
- Mancha de corte e aterro com **tolerância "sem alteração"** (padrão 5 cm): diferenças menores entre A e B são ruído de medição e ficam fora do mapa. A área sem alteração e os volumes só fora da tolerância vão para o log, e cada classe traz o seu volume.
- Legendas dos mapas mostram o nome da classe (ex.: "Ondulado (8–20%)") em vez do número.

## Novidades da 0.13.1 (correções achadas nos testes com dados do CAR)
- Verificação de pontos: um ponto de cota zero ao lado de um pico escondia o pico; cotas zeradas saem da vizinhança e a busca se repete sem os picos já achados.
- Platô: as curvas do terreno final saíam em dezenas de pedaços junto ao off-set; agora uma curva contínua por cota.
- Mancha de corte e aterro: áreas sem alteração (|A − B| < 1 mm) não aparecem mais como "corte de 0 a ...".
- DXF: nomes de camada perdem só o acento (NÍVEL → NIVEL), não a letra.

## Novidades da 0.13.0
- Poligonal com distância inclinada e ângulo zenital: redução ao horizonte e nivelamento trigonométrico (ΔV = DI·cos z + hi − hs, curvatura e refração opcional com k = 0,13), fechamento altimétrico com tolerância em mm·√km, cotas ajustadas no relatório, no CSV e na camada de vértices (PointZ).
- Assistente de importação de DXF de levantamento (Python puro, DXF ASCII): pontos de POINT, blocos (INSERT, com atributos PONTO/COTA/DESC) e círculos; cota do texto numérico mais próximo; linhas e polilinhas 2D/3D; limite fechado vira polígono; vértices de curvas podem virar pontos cotados.

## Novidades da 0.12.0
- Parâmetros das telas salvos junto com o projeto do QGIS (.qgz) e restaurados ao abri-lo; mudar um parâmetro marca o projeto como modificado.
- Arquivo > Salvar parâmetros como / Abrir parâmetros: arquivo .topolab (JSON) para reaproveitar as configurações em outro projeto; camadas reencontradas pelo id ou pelo nome, com aviso das que faltarem.

## Novidades da 0.11.0
- Linhas de quebra e limite do MDT no volume entre duas superfícies e na mancha de corte e aterro, separados para A e para B; as linhas das duas superfícies viram arestas do TIN composto (com vértice nos cruzamentos entre elas), então a diferença não atravessa taludes, cristas e valas.
- Linhas que cruzam o limite do MDT, ou que não têm cota própria, ganham vértice no cruzamento automaticamente (antes era erro). Só duas linhas com cota própria que se cruzam ainda exigem um vértice comum.
- Correção: os pontos inseridos ao longo do limite do MDT (e de linhas sem cota) pegavam a média das cotas dos cantos, achatando o terreno junto à borda; agora seguem o MDT. Em vértices comuns, a cota de uma linha com cota própria prevalece sobre a do limite.

## Novidades da 0.10.0
- Platô com taludes (Volumes > Platô com taludes e Processing *Platô com taludes*): off-set 3D (crista do corte e pé do aterro), volumes de corte e aterro do platô e dos taludes, cota de equilíbrio com fator de homogeneização, curvas do terreno final e relatório; aviso quando os taludes saem da área do MDT.
- Áreas mais precisas com coordenadas UTM (memorial, poligonal, mapas temáticos): a fórmula do laço passou a centralizar as coordenadas; antes podia perder décimos de m² em polígonos com centenas de vértices.

## Novidades da 0.9.1
- Compatível com QGIS 4 / Qt6: enums do Qt na forma qualificada (`Qt.WindowType.Window`), `exec()` no lugar de `exec_()`, tipos de campo por `QMetaType` e enums do QGIS resolvidos em `compat.py` (nome novo, com o antigo de reserva).
- Roteiro perimétrico: polígonos voltam a ser reconhecidos como fechados no QGIS 4.
- Linhas de quebra que se cruzam: a mensagem agora aponta o ponto do cruzamento.
- Relatórios de volumes e da poligonal legíveis em temas escuros do QGIS (exibidos sobre fundo branco).

## Recursos
- Assistente de importação de pontos CSV/TXT: detecta separador, decimal (vírgula/ponto), cabeçalho e codificação; escolha da ordem das colunas (inclui Norte/Leste invertidos) com prévia; reporta linhas ignoradas
- Abertura direta de DXF, Shapefile, GeoPackage, GeoJSON, KML/GPX e GeoTIFF
- Guia rápido (Ajuda > Guia rápido, F1)
- Linhas de quebra e limite do MDT: as linhas viram arestas do TIN (Delaunay conforme: pontos extras sobre a linha, com cota interpolada) e o limite (polígono com furos) exclui triângulos externos; vale em curvas, volume contra cota, platô, perfil, seções, mapas e também no volume e na mancha entre duas superfícies (linhas e limite próprios de A e de B)
- Verificação de qualidade dos pontos: cota zerada/inválida, duplicados (com cota igual ou diferente), pontos muito próximos, picos de cota (plano local nos vizinhos) e IDs repetidos; camada de pontos sinalizados e relatório
- Mapas temáticos sobre o TIN: declividade (classes EMBRAPA ou suas), faixas de elevação (recortadas nas curvas), inundação (área e volume abaixo de uma cota) e manchas de corte/aterro; com estilo automático
- Roteiro perimétrico e memorial a partir de camadas (azimutes e distâncias das coordenadas) e leitura de memorial em texto com restituição da geometria
- MDE em raster -> pontos cotados (Processing: *MDE (raster) em pontos cotados*), para usar em curvas, volumes, perfis e seções
- Exportação de camadas para DXF R12 (pontos com texto, polilinhas 3D, polígonos), escritor em Python puro validado com leitor independente
- Planilha de poligonal: fechada, enquadrada ou aberta; ângulos em DMS/decimal/DDD.MMSS à direita ou à esquerda; fechamento angular e linear com tolerâncias definidas por você; ajuste (Bowditch ou regra do trânsito); coordenadas, área, relatório HTML, CSV, camadas e rascunho de memorial descritivo
- Janela independente com etapas: Pontos, Superfície e curvas, Volumes (perfis/seções e relatório PDF: fase 3)
- Processing > TopoLab:
  - TIN e curvas de nível
  - Volume contra cota de referência
  - Volume entre duas superfícies (original x final)
- Recorte opcional dos volumes por polígono(s), com furos (exato por triângulo)
- Relatório HTML dos volumes
- Perfil longitudinal e seções transversais ao longo de um eixo (estacas de 20 m), com áreas de corte/aterro contra um greide, volumes pela média das áreas, gráfico na janela e exportação CSV
  - Processing: *Perfil longitudinal* e *Seções transversais*
- Núcleo em Python puro (`core/`), testável fora do QGIS

## Instalação
1. Compacte a pasta `topolab/` em ZIP (a pasta deve ser a raiz do ZIP).
2. QGIS > Complementos > Gerenciar e instalar > Instalar a partir de ZIP.
3. Clique no ícone TopoLab (barra de ferramentas ou menu "TopoLab") para abrir a janela.

## Convenções de seções
- Estaqueamento a partir do 1º vértice do eixo; deslocamento positivo = **direita** do eixo.
- Volume entre seções = média das áreas x distância (superestima em curvas fechadas). Seções fora do TIN ficam de fora e são sinalizadas.

## Convenções de volume
- Corte: terreno acima da referência (ou superfície A acima da B).
- Aterro: terreno abaixo da referência (ou A abaixo de B).
- Saldo = corte - aterro. Unidades = unidades do CRS (use CRS projetado, UTM).

## Limitações (v0.15.0)
- DXF: só ASCII (binário não); arcos de polilinha viram retas entre os vértices; SPLINE, HATCH e 3DFACE não são importados (o assistente informa quantos). Textos de cota precisam de casas decimais (inteiros são tratados como número do ponto).
- Linhas de quebra com cota própria que se cruzam precisam de um vértice comum (a cota no cruzamento seria ambígua).
- Platô com taludes: um único platô horizontal por cálculo (todas as feições na mesma cota), sem rampas; bermas com a mesma altura e largura no corte e no aterro, contadas a partir da borda do platô; cantos convexos arredondados. Volumes integrados numa malha de células (erro cai com o quadrado da célula; em testes com fórmulas fechadas, abaixo de 0,02%); áreas de corte e aterro com precisão de uma célula.
- Polígonos de recorte sobrepostos na mesma camada se anulam (regra par-ímpar): use polígonos disjuntos.
- Polígonos com milhares de vértices deixam o recorte mais lento.
- Volume entre superfícies usa TIN composto: exato ao longo das linhas de quebra e limites; fora delas, aproximação onde arestas comuns de A e de B se cruzam.
- Verificação de pontos, MDE→pontos e o cálculo do perfil na tela ainda rodam na linha principal (rápidos nos casos usuais). O cancelamento acontece entre etapas: pode levar até o fim do TIN em andamento.

## Testes do núcleo
    pip install pytest numpy scipy
    pytest topolab/tests   # a partir da pasta acima de topolab/
