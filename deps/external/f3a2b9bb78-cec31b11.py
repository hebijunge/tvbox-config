import sys
import re
import json
from base.spider import Spider


class Spider(Spider):
    """
    全国广播电台 - 蜻蜓FM源
    支持三种分组：总列表（不分类）、按省份、按内容（音乐/新闻/其他）
    """
    
    # ---------- 全部广播数据（来自蜻蜓FM） ----------
    RADIO_DATA = """北京,#genre#
北京新闻广播,https://lhttp-hw.qtfm.cn/live/339/64k.mp3
北京交通广播,https://lhttp-hw.qtfm.cn/live/336/64k.mp3
北京文艺广播,https://lhttp-hw.qtfm.cn/live/333/64k.mp3
959年代音乐怀旧好声音,https://lhttp-hw.qtfm.cn/live/5021381/64k.mp3
北京音乐广播,https://lhttp-hw.qtfm.cn/live/332/64k.mp3
北京城市广播,https://lhttp-hw.qtfm.cn/live/345/64k.mp3
1079音乐有话说,https://lhttp-hw.qtfm.cn/live/20211619/64k.mp3
京津冀之声,https://lhttp-hw.qtfm.cn/live/5022463/64k.mp3
流行音乐广播999正青春,https://lhttp-hw.qtfm.cn/live/20211620/64k.mp3
北京大兴人民广播电台FM986,https://lhttp-hw.qtfm.cn/live/5021739/64k.mp3
上海,#genre#
上海新闻广播,https://lhttp-hw.qtfm.cn/live/270/64k.mp3
第一财经广播,https://lhttp-hw.qtfm.cn/live/276/64k.mp3
上海流行音乐LoveRadio,https://lhttp-hw.qtfm.cn/live/273/64k.mp3
上海动感101,https://lhttp-hw.qtfm.cn/live/274/64k.mp3
上海交通广播电台,https://lhttp-hw.qtfm.cn/live/266/64k.mp3
长三角之声,https://lhttp-hw.qtfm.cn/live/275/64k.mp3
上海戏曲广播,https://lhttp-hw.qtfm.cn/live/269/64k.mp3
上海经典947,https://lhttp-hw.qtfm.cn/live/267/64k.mp3
上海沸点100音乐广播,https://lhttp-hw.qtfm.cn/live/5022341/64k.mp3
东上海之声FM106.5,https://lhttp-hw.qtfm.cn/live/21355/64k.mp3
金山区广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/4022/64k.mp3
天津,#genre#
天津滨海100.5,https://lhttp-hw.qtfm.cn/live/20003/64k.mp3
经典FM1008,https://lhttp-hw.qtfm.cn/live/20212227/64k.mp3
重庆,#genre#
938重庆私家车广播,https://lhttp-hw.qtfm.cn/live/1502/64k.mp3
重庆之声,https://lhttp-hw.qtfm.cn/live/1498/64k.mp3
重庆交通广播,https://lhttp-hw.qtfm.cn/live/1500/64k.mp3
重庆音乐广播,https://lhttp-hw.qtfm.cn/live/647/64k.mp3
重庆巴渝之声,https://lhttp-hw.qtfm.cn/live/5022385/64k.mp3
重庆嘉陵之声FM88.7,https://lhttp-hw.qtfm.cn/live/20211692/64k.mp3
100.7重庆永川之声,https://lhttp-hw.qtfm.cn/live/20210236/64k.mp3
大足人民广播电台,https://lhttp-hw.qtfm.cn/live/20211676/64k.mp3
万盛融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/15318480/64k.mp3
重庆南川97.0,https://lhttp-hw.qtfm.cn/live/15318405/64k.mp3
梁平之声,https://lhttp-hw.qtfm.cn/live/20211646/64k.mp3
綦江综合广播,https://lhttp-hw.qtfm.cn/live/20500201/64k.mp3
唐山交通文艺,https://lhttp-hw.qtfm.cn/live/1659/64k.mp3
唐山新闻综合,https://lhttp-hw.qtfm.cn/live/1657/64k.mp3
唐山音乐广播,https://lhttp-hw.qtfm.cn/live/4871/64k.mp3
唐山小说娱乐广播,https://lhttp-hw.qtfm.cn/live/1660/64k.mp3
唐山经济生活广播,https://lhttp-hw.qtfm.cn/live/15318431/64k.mp3
吉林,#genre#
吉林新闻综合广播,https://lhttp-hw.qtfm.cn/live/4953/64k.mp3
长春交通之声,https://lhttp-hw.qtfm.cn/live/4967/64k.mp3
吉林交通广播,https://lhttp-hw.qtfm.cn/live/4945/64k.mp3
吉林资讯广播,https://lhttp-hw.qtfm.cn/live/3978/64k.mp3
长春广播电视台 FM88.0,https://lhttp-hw.qtfm.cn/live/4850/64k.mp3
吉林市交通台 FM939,https://lhttp-hw.qtfm.cn/live/1819/64k.mp3
延边新闻广播,https://lhttp-hw.qtfm.cn/live/5022488/64k.mp3
吉林市广播电视台经济广播,https://lhttp-hw.qtfm.cn/live/1823/64k.mp3
吉林旅游广播,https://lhttp-hw.qtfm.cn/live/20487/64k.mp3
松原交通文艺广播,https://lhttp-hw.qtfm.cn/live/20212256/64k.mp3
白山交通广播FM950,https://lhttp-hw.qtfm.cn/live/5083/64k.mp3
吉林乡村广播,https://lhttp-hw.qtfm.cn/live/3977/64k.mp3
吉林音乐广播,https://lhttp-hw.qtfm.cn/live/1831/64k.mp3
通化交通文艺广播,https://lhttp-hw.qtfm.cn/live/20500120/64k.mp3
1063城市生活广播,https://lhttp-hw.qtfm.cn/live/4984/64k.mp3
长春新闻广播,https://lhttp-hw.qtfm.cn/live/5013/64k.mp3
延边广播朝鲜语综合频率,https://lhttp-hw.qtfm.cn/live/20324/64k.mp3
吉林经济广播FM95.3AM846,https://lhttp-hw.qtfm.cn/live/3976/64k.mp3
吉林市音乐广播,https://lhttp-hw.qtfm.cn/live/20211679/64k.mp3
延吉综合广播（朝鲜语）,https://lhttp-hw.qtfm.cn/live/5022144/64k.mp3
延吉交通之声,https://lhttp-hw.qtfm.cn/live/15318331/64k.mp3
公主岭交通之声,https://lhttp-hw.qtfm.cn/live/20212386/64k.mp3
吉林健康娱乐广播,https://lhttp-hw.qtfm.cn/live/4952/64k.mp3
辉南综合广播,https://lhttp-hw.qtfm.cn/live/20211566/64k.mp3
901综合文艺广播,https://lhttp-hw.qtfm.cn/live/20211585/64k.mp3
四平交通文艺台,https://lhttp-hw.qtfm.cn/live/5022465/64k.mp3
梅河口人民广播电台城市之声,https://lhttp-hw.qtfm.cn/live/20500115/64k.mp3
松原新闻综合广播,https://lhttp-hw.qtfm.cn/live/5079/64k.mp3
松原大众生活广播,https://lhttp-hw.qtfm.cn/live/5082/64k.mp3
CBS 파워라디오 [Music FM],https://lhttp-hw.qtfm.cn/live/15318233/64k.mp3
1046延边旅游生活广播,https://lhttp-hw.qtfm.cn/live/5022438/64k.mp3
魅力FM1008,https://lhttp-hw.qtfm.cn/live/5021975/64k.mp3
榆树广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500231/64k.mp3
梨树电台北方交通之声,https://lhttp-hw.qtfm.cn/live/5022538/64k.mp3
四平综合广播,https://lhttp-hw.qtfm.cn/live/15318197/64k.mp3
伊通人民广播电台,https://lhttp-hw.qtfm.cn/live/20500154/64k.mp3
辽宁,#genre#
沈阳之声,https://lhttp-hw.qtfm.cn/live/20024/64k.mp3
辽宁交通广播FM97.5,https://lhttp-hw.qtfm.cn/live/20025/64k.mp3
大连体育广播,https://lhttp-hw.qtfm.cn/live/1085/64k.mp3
沈阳都市广播,https://lhttp-hw.qtfm.cn/live/1099/64k.mp3
沈阳交通广播FM98.6,https://lhttp-hw.qtfm.cn/live/1101/64k.mp3
抚顺交通广播,https://lhttp-hw.qtfm.cn/live/1094/64k.mp3
沈阳生活广播,https://lhttp-hw.qtfm.cn/live/1102/64k.mp3
辽阳交通文艺广播,https://lhttp-hw.qtfm.cn/live/5022030/64k.mp3
辽宁乡村广播,https://lhttp-hw.qtfm.cn/live/20018/64k.mp3
辽宁经济广播,https://lhttp-hw.qtfm.cn/live/20019/64k.mp3
辽宁经典音乐广播,https://lhttp-hw.qtfm.cn/live/20021/64k.mp3
辽宁资讯广播fm90.6大连分台,https://lhttp-hw.qtfm.cn/live/5022018/64k.mp3
大连交通广播,https://lhttp-hw.qtfm.cn/live/3997/64k.mp3
辽宁综合广播——辽宁之声,https://lhttp-hw.qtfm.cn/live/1103/64k.mp3
普兰店FM90.8,https://lhttp-hw.qtfm.cn/live/20212414/64k.mp3
瓦房店广播电视台新闻综合广播,https://lhttp-hw.qtfm.cn/live/20500094/64k.mp3
FM106.9海城综合广播,https://lhttp-hw.qtfm.cn/live/15318107/64k.mp3
朝阳县人民广播电台FM104,https://lhttp-hw.qtfm.cn/live/20212211/64k.mp3
大连都市广播,https://lhttp-hw.qtfm.cn/live/1086/64k.mp3
大连1043,https://lhttp-hw.qtfm.cn/live/15318307/64k.mp3
大连新闻广播,https://lhttp-hw.qtfm.cn/live/1089/64k.mp3
FM97.0庄河融媒广播,https://lhttp-hw.qtfm.cn/live/5022473/64k.mp3
抚顺综合广播,https://lhttp-hw.qtfm.cn/live/20158/64k.mp3
大连1067,https://lhttp-hw.qtfm.cn/live/1084/64k.mp3
东港融媒综合广播,https://lhttp-hw.qtfm.cn/live/5022186/64k.mp3
FM105.6,https://lhttp-hw.qtfm.cn/live/5022520/64k.mp3
辽阳综合广播,https://lhttp-hw.qtfm.cn/live/5022447/64k.mp3
朝阳交通广播,https://lhttp-hw.qtfm.cn/live/20719/64k.mp3
朝阳新闻综合广播,https://lhttp-hw.qtfm.cn/live/20715/64k.mp3
桓仁广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022699/64k.mp3
绥中综合广播,https://lhttp-hw.qtfm.cn/live/20211705/64k.mp3
朝阳经济广播,https://lhttp-hw.qtfm.cn/live/5021880/64k.mp3
新民人民广播电台,https://lhttp-hw.qtfm.cn/live/5022535/64k.mp3
凌源广播电台,https://lhttp-hw.qtfm.cn/live/15318298/64k.mp3
黑山人民广播电台,https://lhttp-hw.qtfm.cn/live/20500119/64k.mp3
建平广播电视台,https://lhttp-hw.qtfm.cn/live/15318332/64k.mp3
内蒙古,#genre#
FM94.9包头综合广播,https://lhttp-hw.qtfm.cn/live/1889/64k.mp3
内蒙古交通之声,https://lhttp-hw.qtfm.cn/live/1884/64k.mp3
赤峰综合广播,https://lhttp-hw.qtfm.cn/live/1896/64k.mp3
内蒙古音乐之声,https://lhttp-hw.qtfm.cn/live/1886/64k.mp3
呼和浩特综合广播,https://lhttp-hw.qtfm.cn/live/5021543/64k.mp3
内蒙古新闻综合广播,https://lhttp-hw.qtfm.cn/live/1883/64k.mp3
包头交通广播,https://lhttp-hw.qtfm.cn/live/1890/64k.mp3
赤峰交通广播,https://lhttp-hw.qtfm.cn/live/1899/64k.mp3
包头汽车音乐广播,https://lhttp-hw.qtfm.cn/live/1892/64k.mp3
内蒙古绿野之声广播,https://lhttp-hw.qtfm.cn/live/1888/64k.mp3
内蒙古蒙古语广播,https://lhttp-hw.qtfm.cn/live/1882/64k.mp3
鄂尔多斯交通文体广播,https://lhttp-hw.qtfm.cn/live/20352/64k.mp3
呼和浩特交通广播,https://lhttp-hw.qtfm.cn/live/5021545/64k.mp3
FM896鄂尔多斯之声,https://lhttp-hw.qtfm.cn/live/20350/64k.mp3
赤峰蒙古语综合广播,https://lhttp-hw.qtfm.cn/live/1897/64k.mp3
内蒙古草原之声广播,https://lhttp-hw.qtfm.cn/live/20973/64k.mp3
赤峰1024,https://lhttp-hw.qtfm.cn/live/1898/64k.mp3
阿拉善综合广播,https://lhttp-hw.qtfm.cn/live/5022521/64k.mp3
乌海综合广播,https://lhttp-hw.qtfm.cn/live/15318706/64k.mp3
包头FM105.9,https://lhttp-hw.qtfm.cn/live/1891/64k.mp3
鄂尔多斯蒙语综合广播,https://lhttp-hw.qtfm.cn/live/20348/64k.mp3
巴彦淖尔文艺生活广播,https://lhttp-hw.qtfm.cn/live/1894/64k.mp3
阿拉善蒙语综合广播,https://lhttp-hw.qtfm.cn/live/5022555/64k.mp3
乌海交通音乐广播,https://lhttp-hw.qtfm.cn/live/15318704/64k.mp3
巴彦淖尔广播电视台 综合广播,https://lhttp-hw.qtfm.cn/live/1893/64k.mp3
巴彦淖尔交通广播,https://lhttp-hw.qtfm.cn/live/1895/64k.mp3
宁夏,#genre#
宁夏交通广播,https://lhttp-hw.qtfm.cn/live/1840/64k.mp3
宁夏音乐广播,https://lhttp-hw.qtfm.cn/live/15318294/64k.mp3
石嘴山综合广播,https://lhttp-hw.qtfm.cn/live/5022563/64k.mp3
甘肃,#genre#
甘肃交通广播,https://lhttp-hw.qtfm.cn/live/3939/64k.mp3
甘肃新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022622/64k.mp3
天水综合广播,https://lhttp-hw.qtfm.cn/live/20460/64k.mp3
甘肃农村广播,https://lhttp-hw.qtfm.cn/live/3941/64k.mp3
张掖新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022096/64k.mp3
FM106.6综合广播,https://lhttp-hw.qtfm.cn/live/15318602/64k.mp3
天水交通广播FM91.9,https://lhttp-hw.qtfm.cn/live/20211613/64k.mp3
定西交通广播,https://lhttp-hw.qtfm.cn/live/20212230/64k.mp3
青海,#genre#
青海交通音乐,https://lhttp-hw.qtfm.cn/live/5009/64k.mp3
西宁新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022282/64k.mp3
青海经济生活广播,https://lhttp-hw.qtfm.cn/live/5008/64k.mp3
FM104.3西宁交通文艺广播,https://lhttp-hw.qtfm.cn/live/5022283/64k.mp3
陕西,#genre#
陕西新闻广播,https://lhttp-hw.qtfm.cn/live/1600/64k.mp3
陕西交通广播,https://lhttp-hw.qtfm.cn/live/1601/64k.mp3
陕西农村广播,https://lhttp-hw.qtfm.cn/live/1602/64k.mp3
西安音乐广播,https://lhttp-hw.qtfm.cn/live/1612/64k.mp3
西安新闻广播,https://lhttp-hw.qtfm.cn/live/1610/64k.mp3
陕西音乐广播,https://lhttp-hw.qtfm.cn/live/4873/64k.mp3
唐诗电台,https://lhttp-hw.qtfm.cn/live/1603/64k.mp3
FM100.7咸阳人民广播电台,https://lhttp-hw.qtfm.cn/live/5022397/64k.mp3
宝鸡综合广播,https://lhttp-hw.qtfm.cn/live/15318125/64k.mp3
宝鸡交通旅游,https://lhttp-hw.qtfm.cn/live/15318128/64k.mp3
陕西青少广播·1055青春有我,https://lhttp-hw.qtfm.cn/live/4885/64k.mp3
渭南广播FM90.9,https://lhttp-hw.qtfm.cn/live/5022389/64k.mp3
西安交通广播,https://lhttp-hw.qtfm.cn/live/1611/64k.mp3
安康综合广播,https://lhttp-hw.qtfm.cn/live/5021861/64k.mp3
安康交通广播,https://lhttp-hw.qtfm.cn/live/5021862/64k.mp3
渭南广播FM102.6,https://lhttp-hw.qtfm.cn/live/5022388/64k.mp3
彬州之声,https://lhttp-hw.qtfm.cn/live/20500035/64k.mp3
韩城交通音乐广播,https://lhttp-hw.qtfm.cn/live/15318413/64k.mp3
河北,#genre#
河北新闻广播,https://lhttp-hw.qtfm.cn/live/1644/64k.mp3
河北音乐广播,https://lhttp-hw.qtfm.cn/live/1649/64k.mp3
河北交通广播,https://lhttp-hw.qtfm.cn/live/1646/64k.mp3
经典音乐 FM90.5,https://lhttp-hw.qtfm.cn/live/20212269/64k.mp3
邯郸新闻综合广播,https://lhttp-hw.qtfm.cn/live/5072/64k.mp3
石家庄新闻广播,https://lhttp-hw.qtfm.cn/live/1652/64k.mp3
怀旧金曲964,https://lhttp-hw.qtfm.cn/live/5021555/64k.mp3
献县人民广播电台,https://lhttp-hw.qtfm.cn/live/5022603/64k.mp3
任丘融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/5022470/64k.mp3
邯郸交通广播,https://lhttp-hw.qtfm.cn/live/3950/64k.mp3
河北旅游文化广播,https://lhttp-hw.qtfm.cn/live/1651/64k.mp3
河北综合广播,https://lhttp-hw.qtfm.cn/live/20500111/64k.mp3
邯郸都市生活广播,https://lhttp-hw.qtfm.cn/live/3951/64k.mp3
畅行951,https://lhttp-hw.qtfm.cn/live/3948/64k.mp3
秦皇岛交通广播,https://lhttp-hw.qtfm.cn/live/20849/64k.mp3
保定新闻广播,https://lhttp-hw.qtfm.cn/live/5022440/64k.mp3
武安融媒综合广播,https://lhttp-hw.qtfm.cn/live/5022474/64k.mp3
秦皇岛新闻综合广播,https://lhttp-hw.qtfm.cn/live/20855/64k.mp3
河北故事广播,https://lhttp-hw.qtfm.cn/live/1645/64k.mp3
石家庄交通广播,https://lhttp-hw.qtfm.cn/live/1655/64k.mp3
年代965经典音乐广播,https://lhttp-hw.qtfm.cn/live/5022038/64k.mp3
衡水湖城之声961,https://lhttp-hw.qtfm.cn/live/5021857/64k.mp3
魏县鸭梨音乐广播,https://lhttp-hw.qtfm.cn/live/20212412/64k.mp3
衡水交通广播925,https://lhttp-hw.qtfm.cn/live/5021940/64k.mp3
唐山交通文艺,https://lhttp-hw.qtfm.cn/live/1659/64k.mp3
石家庄音乐广播,https://lhttp-hw.qtfm.cn/live/1654/64k.mp3
保定1058飞扬调频汽车音乐广播,https://lhttp-hw.qtfm.cn/live/5021803/64k.mp3
河北农民广播,https://lhttp-hw.qtfm.cn/live/1650/64k.mp3
河间市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/15318503/64k.mp3
秦皇岛音乐广播,https://lhttp-hw.qtfm.cn/live/20835/64k.mp3
唐山新闻综合,https://lhttp-hw.qtfm.cn/live/1657/64k.mp3
河北文艺广播,https://lhttp-hw.qtfm.cn/live/4868/64k.mp3
沧州音乐广播FM103.6,https://lhttp-hw.qtfm.cn/live/5021902/64k.mp3
张家口交通广播,https://lhttp-hw.qtfm.cn/live/5021910/64k.mp3
河北生活广播,https://lhttp-hw.qtfm.cn/live/4867/64k.mp3
承德综合广播,https://lhttp-hw.qtfm.cn/live/20500052/64k.mp3
廊坊飞扬105,https://lhttp-hw.qtfm.cn/live/20211678/64k.mp3
邢台综合广播,https://lhttp-hw.qtfm.cn/live/20211628/64k.mp3
定州融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20211638/64k.mp3
秦皇岛1038私家车广播,https://lhttp-hw.qtfm.cn/live/20859/64k.mp3
张家口986音乐广播,https://lhttp-hw.qtfm.cn/live/5021801/64k.mp3
张家口1074综合广播,https://lhttp-hw.qtfm.cn/live/15318285/64k.mp3
FM104.8 保定民生广播,https://lhttp-hw.qtfm.cn/live/20168/64k.mp3
邯郸音乐广播,https://lhttp-hw.qtfm.cn/live/4601/64k.mp3
唐山音乐广播,https://lhttp-hw.qtfm.cn/live/4871/64k.mp3
衡水综合广播,https://lhttp-hw.qtfm.cn/live/5022040/64k.mp3
邢台交通音乐广播,https://lhttp-hw.qtfm.cn/live/15318481/64k.mp3
张家口旅游广播,https://lhttp-hw.qtfm.cn/live/5021507/64k.mp3
沧州交通广播,https://lhttp-hw.qtfm.cn/live/3954/64k.mp3
唐山小说娱乐广播,https://lhttp-hw.qtfm.cn/live/1660/64k.mp3
肃宁融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500183/64k.mp3
976承德交通文艺广播,https://lhttp-hw.qtfm.cn/live/15318216/64k.mp3
肥乡人民广播电台,https://lhttp-hw.qtfm.cn/live/20500104/64k.mp3
沧州1058汽车音乐广播,https://lhttp-hw.qtfm.cn/live/5021914/64k.mp3
承德旅游生活广播,https://lhttp-hw.qtfm.cn/live/15318158/64k.mp3
泊头人民广播电台,https://lhttp-hw.qtfm.cn/live/20500164/64k.mp3
唐山经济生活广播,https://lhttp-hw.qtfm.cn/live/15318431/64k.mp3
经典913,https://lhttp-hw.qtfm.cn/live/20500222/64k.mp3
青春调频 FM105.4,https://lhttp-hw.qtfm.cn/live/20212203/64k.mp3
久久金曲 FM99.9,https://lhttp-hw.qtfm.cn/live/20211694/64k.mp3
邢台经济生活广播,https://lhttp-hw.qtfm.cn/live/15318265/64k.mp3
FM107.9,https://lhttp-hw.qtfm.cn/live/20500225/64k.mp3
欢乐调频,https://lhttp-hw.qtfm.cn/live/15318317/64k.mp3
FM93.0霸州汽车音乐广播,https://lhttp-hw.qtfm.cn/live/20211658/64k.mp3
年代995,https://lhttp-hw.qtfm.cn/live/20500202/64k.mp3
鹿泉融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20211668/64k.mp3
怀来人民广播电台 FM95.4,https://lhttp-hw.qtfm.cn/live/5022643/64k.mp3
辛集融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/5021959/64k.mp3
磁县融媒综合广播,https://lhttp-hw.qtfm.cn/live/20500116/64k.mp3
沧州新闻广播,https://lhttp-hw.qtfm.cn/live/5021901/64k.mp3
曲阳融媒FM90.4,https://lhttp-hw.qtfm.cn/live/20500219/64k.mp3
FM98.6邢台信都融媒广播,https://lhttp-hw.qtfm.cn/live/20500196/64k.mp3
深州综合频率FM106.9,https://lhttp-hw.qtfm.cn/live/20500238/64k.mp3
FM106.2邢台信都融媒广播,https://lhttp-hw.qtfm.cn/live/20500096/64k.mp3
邢台爱在104,https://lhttp-hw.qtfm.cn/live/5022484/64k.mp3
崇礼综合广播,https://lhttp-hw.qtfm.cn/live/20500100/64k.mp3
动听913（宣化区融媒体中心综合广播）,https://lhttp-hw.qtfm.cn/live/15318538/64k.mp3
FM963景县融媒综合广播,https://lhttp-hw.qtfm.cn/live/20500192/64k.mp3
山西,#genre#
880山西交通广播,https://lhttp-hw.qtfm.cn/live/20007/64k.mp3
FM107太原交通广播,https://lhttp-hw.qtfm.cn/live/4900/64k.mp3
山西音乐广播,https://lhttp-hw.qtfm.cn/live/4932/64k.mp3
山西综合广播FM904,https://lhttp-hw.qtfm.cn/live/20491/64k.mp3
FM912太原综合广播,https://lhttp-hw.qtfm.cn/live/20006/64k.mp3
山西健康之声,https://lhttp-hw.qtfm.cn/live/20470/64k.mp3
FM101.5山西文艺广播,https://lhttp-hw.qtfm.cn/live/20485/64k.mp3
958电台山西经济广播,https://lhttp-hw.qtfm.cn/live/20501/64k.mp3
运城文艺广播,https://lhttp-hw.qtfm.cn/live/1191/64k.mp3
FM1044太原经济广播,https://lhttp-hw.qtfm.cn/live/4018/64k.mp3
山西故事广播,https://lhttp-hw.qtfm.cn/live/5022511/64k.mp3
大同广播电视台新闻综合广播,https://lhttp-hw.qtfm.cn/live/20211690/64k.mp3
太原老年之声广播,https://lhttp-hw.qtfm.cn/live/20211701/64k.mp3
阳泉综合广播,https://lhttp-hw.qtfm.cn/live/15318568/64k.mp3
大同交通广播,https://lhttp-hw.qtfm.cn/live/5022396/64k.mp3
长治综合广播,https://lhttp-hw.qtfm.cn/live/5021874/64k.mp3
山西农村广播,https://lhttp-hw.qtfm.cn/live/1186/64k.mp3
运城综合广播,https://lhttp-hw.qtfm.cn/live/1190/64k.mp3
阳泉交通广播,https://lhttp-hw.qtfm.cn/live/15318165/64k.mp3
FM1026太原音乐广播,https://lhttp-hw.qtfm.cn/live/1185/64k.mp3
晋城新闻综合广播FM1072,https://lhttp-hw.qtfm.cn/live/1188/64k.mp3
大同经济文艺广播,https://lhttp-hw.qtfm.cn/live/20211689/64k.mp3
晋城交通广播,https://lhttp-hw.qtfm.cn/live/1189/64k.mp3
长治交通广播,https://lhttp-hw.qtfm.cn/live/5021851/64k.mp3
金荔枝经典流行音乐,https://lhttp-hw.qtfm.cn/live/15318194/64k.mp3
吕梁综合广播,https://lhttp-hw.qtfm.cn/live/4020/64k.mp3
阳泉最爱音乐台,https://lhttp-hw.qtfm.cn/live/20211652/64k.mp3
平定综合广播FM101.1,https://lhttp-hw.qtfm.cn/live/5022407/64k.mp3
晋城音乐广播魅力1021,https://lhttp-hw.qtfm.cn/live/5021761/64k.mp3
FM104.1北岳之声,https://lhttp-hw.qtfm.cn/live/20212209/64k.mp3
FM88.7垣曲人民 广播电台,https://lhttp-hw.qtfm.cn/live/20500090/64k.mp3
吕梁交通广播,https://lhttp-hw.qtfm.cn/live/4899/64k.mp3
摩天102,https://lhttp-hw.qtfm.cn/live/20212394/64k.mp3
山东,#genre#
济南新闻广播,https://lhttp-hw.qtfm.cn/live/1667/64k.mp3
济南经济广播,https://lhttp-hw.qtfm.cn/live/1668/64k.mp3
都市101经济广播,https://lhttp-hw.qtfm.cn/live/3995/64k.mp3
青岛新闻广播,https://lhttp-hw.qtfm.cn/live/1673/64k.mp3
济南交通广播,https://lhttp-hw.qtfm.cn/live/1669/64k.mp3
青岛交通广播,https://lhttp-hw.qtfm.cn/live/1676/64k.mp3
山东经济广播,https://lhttp-hw.qtfm.cn/live/20236/64k.mp3
济南故事广播,https://lhttp-hw.qtfm.cn/live/1672/64k.mp3
临沂综合广播,https://lhttp-hw.qtfm.cn/live/3992/64k.mp3
FM92.6 综合广播,https://lhttp-hw.qtfm.cn/live/20176/64k.mp3
山东经典音乐广播,https://lhttp-hw.qtfm.cn/live/20240/64k.mp3
崂山921,https://lhttp-hw.qtfm.cn/live/20212426/64k.mp3
城阳940,https://lhttp-hw.qtfm.cn/live/5022537/64k.mp3
山东音乐广播,https://lhttp-hw.qtfm.cn/live/1665/64k.mp3
济南音乐广播FM88.7,https://lhttp-hw.qtfm.cn/live/1671/64k.mp3
胶州875,https://lhttp-hw.qtfm.cn/live/20211644/64k.mp3
山东文艺广播,https://lhttp-hw.qtfm.cn/live/20238/64k.mp3
936私家车广播,https://lhttp-hw.qtfm.cn/live/1670/64k.mp3
淄博综合广播,https://lhttp-hw.qtfm.cn/live/1678/64k.mp3
淄博私家车广播  FM106.7,https://lhttp-hw.qtfm.cn/live/1679/64k.mp3
青岛经济广播,https://lhttp-hw.qtfm.cn/live/1674/64k.mp3
FM95.2青岛故事广播,https://lhttp-hw.qtfm.cn/live/4956/64k.mp3
即墨融媒综合广播,https://lhttp-hw.qtfm.cn/live/20807/64k.mp3
高密955,https://lhttp-hw.qtfm.cn/live/20212417/64k.mp3
东营交通音乐广播FM98.4,https://lhttp-hw.qtfm.cn/live/20142/64k.mp3
FM107潍坊交通广播,https://lhttp-hw.qtfm.cn/live/4014/64k.mp3
经典音乐广播FM94.8,https://lhttp-hw.qtfm.cn/live/20500097/64k.mp3
青岛文艺广播,https://lhttp-hw.qtfm.cn/live/1675/64k.mp3
烟台综合广播FM101,https://lhttp-hw.qtfm.cn/live/1682/64k.mp3
聊城交通广播,https://lhttp-hw.qtfm.cn/live/5022263/64k.mp3
临沂交通旅游广播,https://lhttp-hw.qtfm.cn/live/3993/64k.mp3
济宁交通广播,https://lhttp-hw.qtfm.cn/live/20087/64k.mp3
青岛音乐体育广播,https://lhttp-hw.qtfm.cn/live/1677/64k.mp3
FM898汽车音乐广播,https://lhttp-hw.qtfm.cn/live/5022382/64k.mp3
临沂音乐广播,https://lhttp-hw.qtfm.cn/live/4017/64k.mp3
枣庄综合广播,https://lhttp-hw.qtfm.cn/live/1686/64k.mp3
烟台交通广播FM103,https://lhttp-hw.qtfm.cn/live/1684/64k.mp3
淄博交通音乐广播,https://lhttp-hw.qtfm.cn/live/1680/64k.mp3
威海新闻电台,https://lhttp-hw.qtfm.cn/live/20669/64k.mp3
聊城综合广播,https://lhttp-hw.qtfm.cn/live/5022264/64k.mp3
菏泽新闻广播,https://lhttp-hw.qtfm.cn/live/20212293/64k.mp3
烟台音乐广播FM105.9,https://lhttp-hw.qtfm.cn/live/1683/64k.mp3
枣庄交通文艺广播,https://lhttp-hw.qtfm.cn/live/1688/64k.mp3
潍坊新闻广播,https://lhttp-hw.qtfm.cn/live/20320/64k.mp3
FM90.7威海音乐广播,https://lhttp-hw.qtfm.cn/live/15318612/64k.mp3
FM88.1潍坊音乐广播,https://lhttp-hw.qtfm.cn/live/15318631/64k.mp3
滕州广播电视台FM99.8,https://lhttp-hw.qtfm.cn/live/5022611/64k.mp3
财富932私家车广播,https://lhttp-hw.qtfm.cn/live/3994/64k.mp3
潍坊933经济广播,https://lhttp-hw.qtfm.cn/live/20839/64k.mp3
FM101.8济宁综合广播,https://lhttp-hw.qtfm.cn/live/4901/64k.mp3
动感955,https://lhttp-hw.qtfm.cn/live/1689/64k.mp3
潍坊1008城市之声,https://lhttp-hw.qtfm.cn/live/20211696/64k.mp3
菏泽交通广播,https://lhttp-hw.qtfm.cn/live/20212294/64k.mp3
105.7滨州文艺音乐广播,https://lhttp-hw.qtfm.cn/live/21341/64k.mp3
FM96.1邹城之声,https://lhttp-hw.qtfm.cn/live/20207732/64k.mp3
聊城经济广播,https://lhttp-hw.qtfm.cn/live/5022262/64k.mp3
FM93.1滨州交通音乐广播,https://lhttp-hw.qtfm.cn/live/20519/64k.mp3
枣庄经济生活广播,https://lhttp-hw.qtfm.cn/live/1687/64k.mp3
潍坊982广播电台,https://lhttp-hw.qtfm.cn/live/4865/64k.mp3
FM92.4安丘924,https://lhttp-hw.qtfm.cn/live/20212216/64k.mp3
寿光市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500211/64k.mp3
FM107济宁生活广播,https://lhttp-hw.qtfm.cn/live/4008/64k.mp3
庆云融媒综合广播,https://lhttp-hw.qtfm.cn/live/5022403/64k.mp3
东营生活广播,https://lhttp-hw.qtfm.cn/live/20211580/64k.mp3
东营综合广播,https://lhttp-hw.qtfm.cn/live/20144/64k.mp3
经典流行音乐动感904,https://lhttp-hw.qtfm.cn/live/20211680/64k.mp3
滨州综合广播,https://lhttp-hw.qtfm.cn/live/5021395/64k.mp3
威海交通广播,https://lhttp-hw.qtfm.cn/live/20671/64k.mp3
FM97.4济南都市广播,https://lhttp-hw.qtfm.cn/live/5022333/64k.mp3
无棣人民广播电台,https://lhttp-hw.qtfm.cn/live/5022198/64k.mp3
曹县融媒体中心综合广播FM93.3,https://lhttp-hw.qtfm.cn/live/5022340/64k.mp3
淄川1055广播,https://lhttp-hw.qtfm.cn/live/20211598/64k.mp3
梁山广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500235/64k.mp3
FM928历城音乐广播,https://lhttp-hw.qtfm.cn/live/20500194/64k.mp3
仙境之声,https://lhttp-hw.qtfm.cn/live/20500112/64k.mp3
声动970,https://lhttp-hw.qtfm.cn/live/20500047/64k.mp3
金乡之声,https://lhttp-hw.qtfm.cn/live/20500085/64k.mp3
章丘之声,https://lhttp-hw.qtfm.cn/live/20212207/64k.mp3
临淄人民广播电台,https://lhttp-hw.qtfm.cn/live/20212204/64k.mp3
成武人民广播电台,https://lhttp-hw.qtfm.cn/live/20211637/64k.mp3
临朐广播电视台FM102.3,https://lhttp-hw.qtfm.cn/live/20500033/64k.mp3
FM91.1邹平人民广播电台,https://lhttp-hw.qtfm.cn/live/5022097/64k.mp3
日照交通生活广播,https://lhttp-hw.qtfm.cn/live/4005/64k.mp3
蒙阴人民广播电台,https://lhttp-hw.qtfm.cn/live/15318571/64k.mp3
周村区广播电视台,https://lhttp-hw.qtfm.cn/live/20500132/64k.mp3
阳信人民广播电台,https://lhttp-hw.qtfm.cn/live/5021991/64k.mp3
广饶人民广播电台FM103.9,https://lhttp-hw.qtfm.cn/live/20500036/64k.mp3
利津广播电视台FM106.2,https://lhttp-hw.qtfm.cn/live/20500138/64k.mp3
滨城综合广播,https://lhttp-hw.qtfm.cn/live/20500168/64k.mp3
安徽,#genre#
安徽综合广播,https://lhttp-hw.qtfm.cn/live/4919/64k.mp3
安徽交通广播,https://lhttp-hw.qtfm.cn/live/1949/64k.mp3
安徽音乐广播,https://lhttp-hw.qtfm.cn/live/1947/64k.mp3
宿州文艺广播,https://lhttp-hw.qtfm.cn/live/5022400/64k.mp3
安庆综合广播,https://lhttp-hw.qtfm.cn/live/1965/64k.mp3
芜湖综合广播,https://lhttp-hw.qtfm.cn/live/5029/64k.mp3
安徽生活广播,https://lhttp-hw.qtfm.cn/live/1948/64k.mp3
芜湖交通经济广播,https://lhttp-hw.qtfm.cn/live/5027/64k.mp3
安徽戏曲广播,https://lhttp-hw.qtfm.cn/live/1952/64k.mp3
安徽老年广播,https://lhttp-hw.qtfm.cn/live/1951/64k.mp3
安徽农村广播,https://lhttp-hw.qtfm.cn/live/1950/64k.mp3
黄山新闻综合广播,https://lhttp-hw.qtfm.cn/live/1968/64k.mp3
经典983电台,https://lhttp-hw.qtfm.cn/live/20211575/64k.mp3
宿州新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022399/64k.mp3
合肥文艺广播,https://lhttp-hw.qtfm.cn/live/1975/64k.mp3
铜陵新闻综合广播,https://lhttp-hw.qtfm.cn/live/21303/64k.mp3
亳州新闻综合广播,https://lhttp-hw.qtfm.cn/live/20207787/64k.mp3
合肥新闻综合广播,https://lhttp-hw.qtfm.cn/live/20212380/64k.mp3
阜阳综合广播,https://lhttp-hw.qtfm.cn/live/1970/64k.mp3
颍上FM962,https://lhttp-hw.qtfm.cn/live/20500039/64k.mp3
安徽经济广播,https://lhttp-hw.qtfm.cn/live/4916/64k.mp3
FM963界首之声（界首新闻综合广播）,https://lhttp-hw.qtfm.cn/live/20207785/64k.mp3
合肥交通广播,https://lhttp-hw.qtfm.cn/live/1960/64k.mp3
合肥文旅广播,https://lhttp-hw.qtfm.cn/live/1961/64k.mp3
天长人民广播电台,https://lhttp-hw.qtfm.cn/live/4854/64k.mp3
FM93.7 濉溪县广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500240/64k.mp3
安庆交通音乐广播,https://lhttp-hw.qtfm.cn/live/1966/64k.mp3
怀远之声,https://lhttp-hw.qtfm.cn/live/5021993/64k.mp3
芜湖音乐故事广播,https://lhttp-hw.qtfm.cn/live/5028/64k.mp3
蚌埠新闻综合广播,https://lhttp-hw.qtfm.cn/live/20154/64k.mp3
黄山交通旅游广播,https://lhttp-hw.qtfm.cn/live/1969/64k.mp3
宣城交通1061,https://lhttp-hw.qtfm.cn/live/5023/64k.mp3
阜阳经济广播,https://lhttp-hw.qtfm.cn/live/5022571/64k.mp3
淮北综合广播,https://lhttp-hw.qtfm.cn/live/20211648/64k.mp3
蚌埠交通文艺广播,https://lhttp-hw.qtfm.cn/live/4577/64k.mp3
池州综合广播,https://lhttp-hw.qtfm.cn/live/5022373/64k.mp3
宣城广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022/64k.mp3
包河之声电台,https://lhttp-hw.qtfm.cn/live/5022668/64k.mp3
太和县广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/15318579/64k.mp3
阜阳交通广播,https://lhttp-hw.qtfm.cn/live/1971/64k.mp3
淮北交通广播,https://lhttp-hw.qtfm.cn/live/20211647/64k.mp3
安徽旅游广播高速之声,https://lhttp-hw.qtfm.cn/live/15318219/64k.mp3
蚌埠广播电视台经典104.2,https://lhttp-hw.qtfm.cn/live/20152/64k.mp3
铜陵交通生活广播,https://lhttp-hw.qtfm.cn/live/21305/64k.mp3
固镇人民广播电台,https://lhttp-hw.qtfm.cn/live/20500125/64k.mp3
天井湖之声FM1024,https://lhttp-hw.qtfm.cn/live/5021979/64k.mp3
亳州交通音乐广播,https://lhttp-hw.qtfm.cn/live/20212419/64k.mp3
河南,#genre#
郑州新闻广播,https://lhttp-hw.qtfm.cn/live/1220/64k.mp3
1042南阳新闻广播,https://lhttp-hw.qtfm.cn/live/1213/64k.mp3
怀旧好声音,https://lhttp-hw.qtfm.cn/live/1223/64k.mp3
洛阳交通广播,https://lhttp-hw.qtfm.cn/live/1227/64k.mp3
郑州交通广播,https://lhttp-hw.qtfm.cn/live/1211/64k.mp3
郑州经济广播,https://lhttp-hw.qtfm.cn/live/1221/64k.mp3
周口综合广播,https://lhttp-hw.qtfm.cn/live/20212215/64k.mp3
洛阳音乐广播,https://lhttp-hw.qtfm.cn/live/1226/64k.mp3
安阳交通广播,https://lhttp-hw.qtfm.cn/live/2138/64k.mp3
郑州音乐广播,https://lhttp-hw.qtfm.cn/live/4921/64k.mp3
洛阳综合广播,https://lhttp-hw.qtfm.cn/live/1225/64k.mp3
开封交通旅游广播,https://lhttp-hw.qtfm.cn/live/1214/64k.mp3
南阳交通广播,https://lhttp-hw.qtfm.cn/live/1212/64k.mp3
FM893周口交通广播,https://lhttp-hw.qtfm.cn/live/15318700/64k.mp3
991新乡综合广播,https://lhttp-hw.qtfm.cn/live/1228/64k.mp3
濮阳好音乐1023,https://lhttp-hw.qtfm.cn/live/5021461/64k.mp3
驻马店综合广播,https://lhttp-hw.qtfm.cn/live/5022118/64k.mp3
商丘新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022443/64k.mp3
安阳新闻应急广播,https://lhttp-hw.qtfm.cn/live/15318224/64k.mp3
济源新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022142/64k.mp3
许昌广播电视台交通广播FM92.6,https://lhttp-hw.qtfm.cn/live/5022095/64k.mp3
1077新乡交通广播,https://lhttp-hw.qtfm.cn/live/1229/64k.mp3
光山90.1,https://lhttp-hw.qtfm.cn/live/20500029/64k.mp3
焦作交通旅游广播,https://lhttp-hw.qtfm.cn/live/20805/64k.mp3
安阳1008音乐广播,https://lhttp-hw.qtfm.cn/live/2123/64k.mp3
FM91.8郑州私家车广播,https://lhttp-hw.qtfm.cn/live/1222/64k.mp3
鹤壁综合广播,https://lhttp-hw.qtfm.cn/live/5022055/64k.mp3
巩义融媒,https://lhttp-hw.qtfm.cn/live/5022551/64k.mp3
AI潮流音乐台,https://lhttp-hw.qtfm.cn/live/15318300/64k.mp3
FM99.6信阳交通广播,https://lhttp-hw.qtfm.cn/live/15318156/64k.mp3
开封私家车音乐广播,https://lhttp-hw.qtfm.cn/live/4569/64k.mp3
声动890信阳综合广播,https://lhttp-hw.qtfm.cn/live/5021977/64k.mp3
驻马店经济广播,https://lhttp-hw.qtfm.cn/live/5022119/64k.mp3
漯河综合广播,https://lhttp-hw.qtfm.cn/live/5022660/64k.mp3
长垣综合广播FM95.7,https://lhttp-hw.qtfm.cn/live/15318663/64k.mp3
许昌广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022092/64k.mp3
三门峡综合广播,https://lhttp-hw.qtfm.cn/live/5022134/64k.mp3
商丘交通1007,https://lhttp-hw.qtfm.cn/live/5021932/64k.mp3
平顶山新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022420/64k.mp3
濮阳新闻广播,https://lhttp-hw.qtfm.cn/live/20207739/64k.mp3
开封综合广播,https://lhttp-hw.qtfm.cn/live/5022653/64k.mp3
南乐融媒广播,https://lhttp-hw.qtfm.cn/live/20500136/64k.mp3
平顶山交通广播,https://lhttp-hw.qtfm.cn/live/5022421/64k.mp3
经典916,https://lhttp-hw.qtfm.cn/live/20207782/64k.mp3
林州广播电台,https://lhttp-hw.qtfm.cn/live/20211604/64k.mp3
鹤壁交通广播FM99.4,https://lhttp-hw.qtfm.cn/live/5022089/64k.mp3
濮阳FM1053快乐调频,https://lhttp-hw.qtfm.cn/live/20206/64k.mp3
焦作新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022557/64k.mp3
南阳好朋友892汽车音乐电台,https://lhttp-hw.qtfm.cn/live/5022725/64k.mp3
汝州人民广播电台,https://lhttp-hw.qtfm.cn/live/5022650/64k.mp3
项城936,https://lhttp-hw.qtfm.cn/live/15318335/64k.mp3
邓州广播电台,https://lhttp-hw.qtfm.cn/live/20500198/64k.mp3
禹州广播电视台 FM93.4,https://lhttp-hw.qtfm.cn/live/20500210/64k.mp3
快乐903私家车广播,https://lhttp-hw.qtfm.cn/live/5021919/64k.mp3
登封综合广播,https://lhttp-hw.qtfm.cn/live/5022077/64k.mp3
濮阳交通广播,https://lhttp-hw.qtfm.cn/live/1233/64k.mp3
TOP Radio 安阳881,https://lhttp-hw.qtfm.cn/live/20209339/64k.mp3
卧龙综合广播,https://lhttp-hw.qtfm.cn/live/20500113/64k.mp3
洛阳城市993,https://lhttp-hw.qtfm.cn/live/20211321/64k.mp3
新密人民广播电台,https://lhttp-hw.qtfm.cn/live/20500144/64k.mp3
漯河交通广播,https://lhttp-hw.qtfm.cn/live/5022452/64k.mp3
汤阴融媒综合广播,https://lhttp-hw.qtfm.cn/live/20500205/64k.mp3
开封祥符广播919,https://lhttp-hw.qtfm.cn/live/20500156/64k.mp3
通许融媒1026,https://lhttp-hw.qtfm.cn/live/20500157/64k.mp3
郏县886,https://lhttp-hw.qtfm.cn/live/5022022/64k.mp3
FM98.9三门峡交通文艺广播,https://lhttp-hw.qtfm.cn/live/15318227/64k.mp3
新县FM106.2,https://lhttp-hw.qtfm.cn/live/20500056/64k.mp3
FM105.9项城人民广播电台,https://lhttp-hw.qtfm.cn/live/20210757/64k.mp3
兰考人民广播电台,https://lhttp-hw.qtfm.cn/live/20500167/64k.mp3
卫辉综合广播92.5,https://lhttp-hw.qtfm.cn/live/20500152/64k.mp3
乐享1007,https://lhttp-hw.qtfm.cn/live/20500141/64k.mp3
正阳综合广播,https://lhttp-hw.qtfm.cn/live/20212397/64k.mp3
湖北,#genre#
湖北之声,https://lhttp-hw.qtfm.cn/live/1303/64k.mp3
武汉经济广播,https://lhttp-hw.qtfm.cn/live/20200/64k.mp3
楚天交通广播,https://lhttp-hw.qtfm.cn/live/1291/64k.mp3
襄阳交通音乐广播,https://lhttp-hw.qtfm.cn/live/1308/64k.mp3
武汉经典音乐广播,https://lhttp-hw.qtfm.cn/live/1297/64k.mp3
武汉新闻广播,https://lhttp-hw.qtfm.cn/live/20198/64k.mp3
湖北经典音乐广播,https://lhttp-hw.qtfm.cn/live/1296/64k.mp3
襄阳之声,https://lhttp-hw.qtfm.cn/live/1307/64k.mp3
武汉交通广播,https://lhttp-hw.qtfm.cn/live/4665/64k.mp3
黄石交通广播,https://lhttp-hw.qtfm.cn/live/3964/64k.mp3
荆门综合广播,https://lhttp-hw.qtfm.cn/live/20211577/64k.mp3
十堰交通音乐广播,https://lhttp-hw.qtfm.cn/live/20342/64k.mp3
十堰综合广播,https://lhttp-hw.qtfm.cn/live/20338/64k.mp3
宜昌交通广播,https://lhttp-hw.qtfm.cn/live/20563/64k.mp3
荆州广播电视台90.1汽车广播,https://lhttp-hw.qtfm.cn/live/1312/64k.mp3
湖北经济广播,https://lhttp-hw.qtfm.cn/live/1295/64k.mp3
宜昌音乐广播,https://lhttp-hw.qtfm.cn/live/20567/64k.mp3
武穴人民广播电台,https://lhttp-hw.qtfm.cn/live/5022071/64k.mp3
咸宁综合广播,https://lhttp-hw.qtfm.cn/live/5067/64k.mp3
黄冈新闻综合广播,https://lhttp-hw.qtfm.cn/live/1301/64k.mp3
孝感交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022063/64k.mp3
仙桃人民广播电台,https://lhttp-hw.qtfm.cn/live/20211562/64k.mp3
襄阳文化教育广播,https://lhttp-hw.qtfm.cn/live/5057/64k.mp3
随州综合广播,https://lhttp-hw.qtfm.cn/live/20853/64k.mp3
孝感新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022064/64k.mp3
鄂州广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/21025/64k.mp3
恩施电台新闻综合频率,https://lhttp-hw.qtfm.cn/live/5022718/64k.mp3
恩施电台交通音乐频率,https://lhttp-hw.qtfm.cn/live/5022719/64k.mp3
黄冈交通音乐广播,https://lhttp-hw.qtfm.cn/live/20207776/64k.mp3
长江之声,https://lhttp-hw.qtfm.cn/live/5021868/64k.mp3
宜昌新闻综合广播,https://lhttp-hw.qtfm.cn/live/20565/64k.mp3
随州交通经济广播,https://lhttp-hw.qtfm.cn/live/21027/64k.mp3
魅力FM1064城市生活音乐广播,https://lhttp-hw.qtfm.cn/live/5022716/64k.mp3
蕲春人民广播电台,https://lhttp-hw.qtfm.cn/live/5022252/64k.mp3
公安人民广播电台,https://lhttp-hw.qtfm.cn/live/5063/64k.mp3
天门人民广播电台,https://lhttp-hw.qtfm.cn/live/20500199/64k.mp3
黄梅之声,https://lhttp-hw.qtfm.cn/live/5022280/64k.mp3
都市965汽车音乐广播,https://lhttp-hw.qtfm.cn/live/20500108/64k.mp3
团风综合广播,https://lhttp-hw.qtfm.cn/live/20500189/64k.mp3
红安人民广播电台,https://lhttp-hw.qtfm.cn/live/5022646/64k.mp3
江陵综合广播,https://lhttp-hw.qtfm.cn/live/20500203/64k.mp3
FM92.2应城市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500227/64k.mp3
咸宁交通广播,https://lhttp-hw.qtfm.cn/live/5068/64k.mp3
孝昌964电台,https://lhttp-hw.qtfm.cn/live/15318546/64k.mp3
云梦综合广播,https://lhttp-hw.qtfm.cn/live/20500204/64k.mp3
监利人民广播电台,https://lhttp-hw.qtfm.cn/live/15318507/64k.mp3
湖南,#genre#
FM88.6长沙音乐广播,https://lhttp-hw.qtfm.cn/live/20847/64k.mp3
长沙FM101.7城市之声,https://lhttp-hw.qtfm.cn/live/4237/64k.mp3
1061长沙交通广播,https://lhttp-hw.qtfm.cn/live/3967/64k.mp3
FM102.2亲子智慧电台,https://lhttp-hw.qtfm.cn/live/4930/64k.mp3
FM105.0长沙新闻广播,https://lhttp-hw.qtfm.cn/live/4877/64k.mp3
Easy Fm,https://lhttp-hw.qtfm.cn/live/5022391/64k.mp3
FM106.8常德鼎广电台,https://lhttp-hw.qtfm.cn/live/5021860/64k.mp3
长沙925电台,https://lhttp-hw.qtfm.cn/live/5022076/64k.mp3
衡阳综合广播,https://lhttp-hw.qtfm.cn/live/15318386/64k.mp3
岳阳交通广播,https://lhttp-hw.qtfm.cn/live/20987/64k.mp3
1028郴州交通旅游广播,https://lhttp-hw.qtfm.cn/live/20867/64k.mp3
株洲交通广播,https://lhttp-hw.qtfm.cn/live/3971/64k.mp3
FM105.6 常德综合广播,https://lhttp-hw.qtfm.cn/live/15318208/64k.mp3
衡阳交通经济广播,https://lhttp-hw.qtfm.cn/live/15318385/64k.mp3
永州新闻综合广播电台,https://lhttp-hw.qtfm.cn/live/15318594/64k.mp3
郴州综合广播,https://lhttp-hw.qtfm.cn/live/20489/64k.mp3
邵阳综合广播,https://lhttp-hw.qtfm.cn/live/20148/64k.mp3
FM97.1常德交通广播,https://lhttp-hw.qtfm.cn/live/15318209/64k.mp3
岳阳新闻综合广播,https://lhttp-hw.qtfm.cn/live/20989/64k.mp3
FM88.1 益阳电台交通频道,https://lhttp-hw.qtfm.cn/live/15318153/64k.mp3
FM104.2湘潭交通广播,https://lhttp-hw.qtfm.cn/live/21269/64k.mp3
FM104.7澧县广播电台,https://lhttp-hw.qtfm.cn/live/15318178/64k.mp3
怀化交通广播,https://lhttp-hw.qtfm.cn/live/5022070/64k.mp3
邵阳经济广播,https://lhttp-hw.qtfm.cn/live/20500058/64k.mp3
怀化电台综合广播,https://lhttp-hw.qtfm.cn/live/5022069/64k.mp3
娄底交通广播,https://lhttp-hw.qtfm.cn/live/20507/64k.mp3
FM88.2湘潭新闻综合广播,https://lhttp-hw.qtfm.cn/live/15318549/64k.mp3
FM99.7 益阳电台综合频道,https://lhttp-hw.qtfm.cn/live/20314/64k.mp3
靖州综合广播,https://lhttp-hw.qtfm.cn/live/20500011/64k.mp3
娄底综合广播,https://lhttp-hw.qtfm.cn/live/21213/64k.mp3
FM99.6宜章县广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/15318691/64k.mp3
桃江人民广播电台,https://lhttp-hw.qtfm.cn/live/20500086/64k.mp3
湘乡广播电台龙城之声,https://lhttp-hw.qtfm.cn/live/15318180/64k.mp3
FM99.2岳阳县综合广播,https://lhttp-hw.qtfm.cn/live/20500129/64k.mp3
江西,#genre#
江西音乐广播,https://lhttp-hw.qtfm.cn/live/1802/64k.mp3
江西新闻广播,https://lhttp-hw.qtfm.cn/live/1809/64k.mp3
南昌交通广播,https://lhttp-hw.qtfm.cn/live/1804/64k.mp3
江西旅游广播FM97.4,https://lhttp-hw.qtfm.cn/live/20133/64k.mp3
赣州综合广播,https://lhttp-hw.qtfm.cn/live/20266/64k.mp3
江西交通广播,https://lhttp-hw.qtfm.cn/live/1811/64k.mp3
FM94.5赣州交通音乐广播,https://lhttp-hw.qtfm.cn/live/4942/64k.mp3
江西潮台969,https://lhttp-hw.qtfm.cn/live/20500092/64k.mp3
南康交通广播,https://lhttp-hw.qtfm.cn/live/5021869/64k.mp3
FM103.2鹰潭交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022036/64k.mp3
新余新闻广播,https://lhttp-hw.qtfm.cn/live/20178/64k.mp3
九江新闻综合900红调频,https://lhttp-hw.qtfm.cn/live/5022729/64k.mp3
江西财经广播（成功992）,https://lhttp-hw.qtfm.cn/live/5021665/64k.mp3
新余交通广播,https://lhttp-hw.qtfm.cn/live/20093/64k.mp3
九江交通广播,https://lhttp-hw.qtfm.cn/live/5021918/64k.mp3
景德镇新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022025/64k.mp3
993萍乡新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022409/64k.mp3
高安电台942,https://lhttp-hw.qtfm.cn/live/20500014/64k.mp3
抚州新闻综合广播,https://lhttp-hw.qtfm.cn/live/20500226/64k.mp3
抚州交通音乐广播,https://lhttp-hw.qtfm.cn/live/20500015/64k.mp3
九江文化旅游广播,https://lhttp-hw.qtfm.cn/live/20212210/64k.mp3
FM104.8鹰潭新闻综合频率,https://lhttp-hw.qtfm.cn/live/5022035/64k.mp3
赣北之声FM94.2,https://lhttp-hw.qtfm.cn/live/5022648/64k.mp3
丰城之声FM88.4,https://lhttp-hw.qtfm.cn/live/20500071/64k.mp3
宜春交通音乐广播,https://lhttp-hw.qtfm.cn/live/20212206/64k.mp3
江苏,#genre#
江苏新闻广播,https://lhttp-hw.qtfm.cn/live/4944/64k.mp3
江苏经典流行音乐,https://lhttp-hw.qtfm.cn/live/4938/64k.mp3
江苏交通广播,https://lhttp-hw.qtfm.cn/live/4054/64k.mp3
苏州音乐广播,https://lhttp-hw.qtfm.cn/live/2803/64k.mp3
苏州交通广播,https://lhttp-hw.qtfm.cn/live/2806/64k.mp3
南京音乐广播,https://lhttp-hw.qtfm.cn/live/4963/64k.mp3
苏州新闻广播,https://lhttp-hw.qtfm.cn/live/2808/64k.mp3
FM93.7无锡新闻综合广播,https://lhttp-hw.qtfm.cn/live/2777/64k.mp3
无锡梁溪之声,https://lhttp-hw.qtfm.cn/live/2782/64k.mp3
徐州新闻综合广播,https://lhttp-hw.qtfm.cn/live/4922/64k.mp3
江苏音乐广播PlayFM897,https://lhttp-hw.qtfm.cn/live/4936/64k.mp3
江苏故事广播,https://lhttp-hw.qtfm.cn/live/20012/64k.mp3
无锡音乐广播,https://lhttp-hw.qtfm.cn/live/2779/64k.mp3
常熟新闻广播,https://lhttp-hw.qtfm.cn/live/2792/64k.mp3
南通交通广播,https://lhttp-hw.qtfm.cn/live/5021533/64k.mp3
江苏财经广播,https://lhttp-hw.qtfm.cn/live/20015/64k.mp3
徐州经典音乐FM942,https://lhttp-hw.qtfm.cn/live/15318160/64k.mp3
苏州儿童广播,https://lhttp-hw.qtfm.cn/live/2807/64k.mp3
常熟广播声动1008,https://lhttp-hw.qtfm.cn/live/2791/64k.mp3
997金陵之声,https://lhttp-hw.qtfm.cn/live/5056/64k.mp3
无锡交通广播,https://lhttp-hw.qtfm.cn/live/2780/64k.mp3
扬州新闻广播,https://lhttp-hw.qtfm.cn/live/5000/64k.mp3
南通音乐广播,https://lhttp-hw.qtfm.cn/live/21275/64k.mp3
苏州生活广播,https://lhttp-hw.qtfm.cn/live/2801/64k.mp3
南通新闻广播,https://lhttp-hw.qtfm.cn/live/21277/64k.mp3
江苏新闻综合广播,https://lhttp-hw.qtfm.cn/live/5055/64k.mp3
徐州音乐广播FM91.9,https://lhttp-hw.qtfm.cn/live/4923/64k.mp3
徐州交通广播,https://lhttp-hw.qtfm.cn/live/4924/64k.mp3
江苏文艺广播,https://lhttp-hw.qtfm.cn/live/20013/64k.mp3
澎湃907,https://lhttp-hw.qtfm.cn/live/2789/64k.mp3
AM1161无锡新闻综合广播,https://lhttp-hw.qtfm.cn/live/2776/64k.mp3
常州新闻广播,https://lhttp-hw.qtfm.cn/live/2798/64k.mp3
无锡经济广播,https://lhttp-hw.qtfm.cn/live/2778/64k.mp3
江苏健康广播,https://lhttp-hw.qtfm.cn/live/20014/64k.mp3
FM104镇江综合广播,https://lhttp-hw.qtfm.cn/live/3984/64k.mp3
常州音乐广播,https://lhttp-hw.qtfm.cn/live/2799/64k.mp3
FM96.7,https://lhttp-hw.qtfm.cn/live/20211632/64k.mp3
常州经济广播,https://lhttp-hw.qtfm.cn/live/2794/64k.mp3
979丹阳之声,https://lhttp-hw.qtfm.cn/live/20207749/64k.mp3
如东新闻综合广播,https://lhttp-hw.qtfm.cn/live/20579/64k.mp3
张家港市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/5021877/64k.mp3
淮安新闻综合,https://lhttp-hw.qtfm.cn/live/4589/64k.mp3
常州交通广播,https://lhttp-hw.qtfm.cn/live/2796/64k.mp3
FM89.1吴江综合广播,https://lhttp-hw.qtfm.cn/live/5022050/64k.mp3
扬州YESFM949,https://lhttp-hw.qtfm.cn/live/2805/64k.mp3
苏州戏曲广播,https://lhttp-hw.qtfm.cn/live/20211622/64k.mp3
淮安交通文艺,https://lhttp-hw.qtfm.cn/live/4586/64k.mp3
扬州交通广播,https://lhttp-hw.qtfm.cn/live/2804/64k.mp3
宁听FM885,https://lhttp-hw.qtfm.cn/live/20500075/64k.mp3
FM96.3镇江文艺广播,https://lhttp-hw.qtfm.cn/live/4605/64k.mp3
扬州电台江都广播,https://lhttp-hw.qtfm.cn/live/5022636/64k.mp3
FM98.8 盐城综合广播,https://lhttp-hw.qtfm.cn/live/20330/64k.mp3
徐州广播FM105,https://lhttp-hw.qtfm.cn/live/20211623/64k.mp3
宿迁交通广播,https://lhttp-hw.qtfm.cn/live/5004/64k.mp3
宜兴交通台,https://lhttp-hw.qtfm.cn/live/3982/64k.mp3
靖江交通音乐广播,https://lhttp-hw.qtfm.cn/live/15318120/64k.mp3
连云港交通广播,https://lhttp-hw.qtfm.cn/live/2775/64k.mp3
大丰FM95.1,https://lhttp-hw.qtfm.cn/live/20211708/64k.mp3
盐城广播FM88.2,https://lhttp-hw.qtfm.cn/live/20332/64k.mp3
滨海1029,https://lhttp-hw.qtfm.cn/live/20207779/64k.mp3
阜宁人民广播,https://lhttp-hw.qtfm.cn/live/20207753/64k.mp3
仪征人民广播电台 FM94.3,https://lhttp-hw.qtfm.cn/live/15318182/64k.mp3
邳州人民广播电台,https://lhttp-hw.qtfm.cn/live/2809/64k.mp3
宿豫人民广播电台,https://lhttp-hw.qtfm.cn/live/5005/64k.mp3
盐城交通广播,https://lhttp-hw.qtfm.cn/live/20326/64k.mp3
FM88.8镇江交通广播,https://lhttp-hw.qtfm.cn/live/3985/64k.mp3
金湖人民广播电台,https://lhttp-hw.qtfm.cn/live/15318464/64k.mp3
淮安经典992,https://lhttp-hw.qtfm.cn/live/15318398/64k.mp3
淮安经济生活,https://lhttp-hw.qtfm.cn/live/4587/64k.mp3
盐城音乐广播,https://lhttp-hw.qtfm.cn/live/5022380/64k.mp3
如皋汽车广播,https://lhttp-hw.qtfm.cn/live/20207734/64k.mp3
886武进之声,https://lhttp-hw.qtfm.cn/live/20150/64k.mp3
南通私家车广播,https://lhttp-hw.qtfm.cn/live/21327/64k.mp3
海门人民广播电台,https://lhttp-hw.qtfm.cn/live/5022640/64k.mp3
宿迁汽车音乐台,https://lhttp-hw.qtfm.cn/live/21265/64k.mp3
睢宁县融媒体中心综合广播 FM93.1,https://lhttp-hw.qtfm.cn/live/20500191/64k.mp3
淮安FM104.2,https://lhttp-hw.qtfm.cn/live/4588/64k.mp3
昆山人民广播电台,https://lhttp-hw.qtfm.cn/live/20500128/64k.mp3
通州人民广播电台,https://lhttp-hw.qtfm.cn/live/20211586/64k.mp3
太仓人民广播电台,https://lhttp-hw.qtfm.cn/live/20207759/64k.mp3
东海994,https://lhttp-hw.qtfm.cn/live/20500220/64k.mp3
赣榆区融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500216/64k.mp3
沛县综合广播,https://lhttp-hw.qtfm.cn/live/20500173/64k.mp3
盱眙县融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500051/64k.mp3
淮安车生活广播,https://lhttp-hw.qtfm.cn/live/5021970/64k.mp3
浙江,#genre#
FM93浙江交通之声,https://lhttp-hw.qtfm.cn/live/4522/64k.mp3
杭州交通91.8电台,https://lhttp-hw.qtfm.cn/live/1133/64k.mp3
浙江之声,https://lhttp-hw.qtfm.cn/live/4518/64k.mp3
浙江FM99.6,https://lhttp-hw.qtfm.cn/live/4521/64k.mp3
西湖之声,https://lhttp-hw.qtfm.cn/live/1163/64k.mp3
嘉兴交通广播,https://lhttp-hw.qtfm.cn/live/1135/64k.mp3
浙江经济广播,https://lhttp-hw.qtfm.cn/live/4519/64k.mp3
浙江音乐调频,https://lhttp-hw.qtfm.cn/live/4866/64k.mp3
FM103.5湖州经济广播,https://lhttp-hw.qtfm.cn/live/2812/64k.mp3
嘉兴综合广播,https://lhttp-hw.qtfm.cn/live/1154/64k.mp3
宁波交通广播,https://lhttp-hw.qtfm.cn/live/1140/64k.mp3
宁波新闻综合广播,https://lhttp-hw.qtfm.cn/live/1138/64k.mp3
杭州FM90.7,https://lhttp-hw.qtfm.cn/live/15318146/64k.mp3
宁波经济广播,https://lhttp-hw.qtfm.cn/live/1152/64k.mp3
嘉兴音乐广播,https://lhttp-hw.qtfm.cn/live/1136/64k.mp3
东阳城市广播,https://lhttp-hw.qtfm.cn/live/21181/64k.mp3
FM105湖州之声,https://lhttp-hw.qtfm.cn/live/2810/64k.mp3
温州交通广播,https://lhttp-hw.qtfm.cn/live/1156/64k.mp3
FM998 舟山新闻综合广播,https://lhttp-hw.qtfm.cn/live/1160/64k.mp3
1047 Nice FM,https://lhttp-hw.qtfm.cn/live/20033/64k.mp3
1003温州音乐之声,https://lhttp-hw.qtfm.cn/live/1149/64k.mp3
瑞安人民广播,https://lhttp-hw.qtfm.cn/live/1143/64k.mp3
永康人民广播电台,https://lhttp-hw.qtfm.cn/live/5022570/64k.mp3
温州新闻广播,https://lhttp-hw.qtfm.cn/live/1155/64k.mp3
慈溪经典车电台,https://lhttp-hw.qtfm.cn/live/5021401/64k.mp3
台州交通广播,https://lhttp-hw.qtfm.cn/live/1146/64k.mp3
湖州交通文艺广播,https://lhttp-hw.qtfm.cn/live/2811/64k.mp3
义乌新闻广播,https://lhttp-hw.qtfm.cn/live/20537/64k.mp3
FM93.6绍兴综合广播,https://lhttp-hw.qtfm.cn/live/5052/64k.mp3
桐乡之声,https://lhttp-hw.qtfm.cn/live/5021791/64k.mp3
温州经济广播,https://lhttp-hw.qtfm.cn/live/1157/64k.mp3
FM104.5旅游之声,https://lhttp-hw.qtfm.cn/live/4524/64k.mp3
乐清人民广播电台,https://lhttp-hw.qtfm.cn/live/20204/64k.mp3
宁波音乐广播私家车986,https://lhttp-hw.qtfm.cn/live/1142/64k.mp3
台州新闻综合 ,https://lhttp-hw.qtfm.cn/live/1145/64k.mp3
1052LoveRadio,https://lhttp-hw.qtfm.cn/live/5022061/64k.mp3
义乌交通广播,https://lhttp-hw.qtfm.cn/live/20533/64k.mp3
FM106.8柯桥人民广播电台,https://lhttp-hw.qtfm.cn/live/2422/64k.mp3
黄岩电台,https://lhttp-hw.qtfm.cn/live/5022671/64k.mp3
诸暨人民广播电台,https://lhttp-hw.qtfm.cn/live/5022482/64k.mp3
FM94.1绍兴交通广播,https://lhttp-hw.qtfm.cn/live/5053/64k.mp3
新昌人民广播电台,https://lhttp-hw.qtfm.cn/live/20212423/64k.mp3
FM97 舟山交通音乐广播,https://lhttp-hw.qtfm.cn/live/1161/64k.mp3
FM96大潮之声,https://lhttp-hw.qtfm.cn/live/5022556/64k.mp3
台州音乐广播,https://lhttp-hw.qtfm.cn/live/1144/64k.mp3
温岭1036电台,https://lhttp-hw.qtfm.cn/live/4567/64k.mp3
玉环广播电台,https://lhttp-hw.qtfm.cn/live/20212390/64k.mp3
衢州新闻综合广播,https://lhttp-hw.qtfm.cn/live/20444/64k.mp3
FM89.8临海人民广播电台,https://lhttp-hw.qtfm.cn/live/5022437/64k.mp3
萧山人民广播电台,https://lhttp-hw.qtfm.cn/live/20500184/64k.mp3
FM989宁海新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022406/64k.mp3
1008可乐台,https://lhttp-hw.qtfm.cn/live/1153/64k.mp3
FM103.5绍兴音乐广播,https://lhttp-hw.qtfm.cn/live/5054/64k.mp3
1022永嘉人民广播电台,https://lhttp-hw.qtfm.cn/live/15318231/64k.mp3
FM93.8,https://lhttp-hw.qtfm.cn/live/1158/64k.mp3
杭州华语之声,https://lhttp-hw.qtfm.cn/live/20505/64k.mp3
FM954龙游电台,https://lhttp-hw.qtfm.cn/live/15318359/64k.mp3
FM101仙居融媒体广播,https://lhttp-hw.qtfm.cn/live/5021908/64k.mp3
FM106.5德清之声,https://lhttp-hw.qtfm.cn/live/5022033/64k.mp3
96.4临安人民广播电台,https://lhttp-hw.qtfm.cn/live/20005/64k.mp3
FM105平阳电台,https://lhttp-hw.qtfm.cn/live/5022624/64k.mp3
天台电台FM91.1,https://lhttp-hw.qtfm.cn/live/5022200/64k.mp3
FM97.3太湖之声,https://lhttp-hw.qtfm.cn/live/5022311/64k.mp3
衢州交通音乐广播,https://lhttp-hw.qtfm.cn/live/20442/64k.mp3
浦江人民广播电台,https://lhttp-hw.qtfm.cn/live/5021924/64k.mp3
三门广播电台,https://lhttp-hw.qtfm.cn/live/15318638/64k.mp3
兰溪电台FM90.8,https://lhttp-hw.qtfm.cn/live/5022526/64k.mp3
福建,#genre#
福建新闻广播,https://lhttp-hw.qtfm.cn/live/1731/64k.mp3
泉州904交通之声,https://lhttp-hw.qtfm.cn/live/15318189/64k.mp3
厦门音乐广播,https://lhttp-hw.qtfm.cn/live/1739/64k.mp3
泉州刺桐之声,https://lhttp-hw.qtfm.cn/live/5022360/64k.mp3
厦门综合广播,https://lhttp-hw.qtfm.cn/live/1737/64k.mp3
泉州广播电视台889新闻综合广播,https://lhttp-hw.qtfm.cn/live/15318346/64k.mp3
厦门交通旅游广播,https://lhttp-hw.qtfm.cn/live/1738/64k.mp3
福建987私家车广播,https://lhttp-hw.qtfm.cn/live/1736/64k.mp3
福建经济广播,https://lhttp-hw.qtfm.cn/live/1732/64k.mp3
893音乐广播,https://lhttp-hw.qtfm.cn/live/4846/64k.mp3
厦门闽南之声广播,https://lhttp-hw.qtfm.cn/live/1740/64k.mp3
福建交通广播,https://lhttp-hw.qtfm.cn/live/1733/64k.mp3
福州人民广播电台左海之声,https://lhttp-hw.qtfm.cn/live/3937/64k.mp3
福州新闻广播,https://lhttp-hw.qtfm.cn/live/5025/64k.mp3
福州交通之声,https://lhttp-hw.qtfm.cn/live/5026/64k.mp3
漳州人民广播电台综合广播,https://lhttp-hw.qtfm.cn/live/1742/64k.mp3
龙岩电台综合广播,https://lhttp-hw.qtfm.cn/live/20709/64k.mp3
海峡之声广播电台,https://lhttp-hw.qtfm.cn/live/1744/64k.mp3
FM881南安广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5021731/64k.mp3
三明新闻综合广播,https://lhttp-hw.qtfm.cn/live/5022100/64k.mp3
厦门892集美广播,https://lhttp-hw.qtfm.cn/live/5022479/64k.mp3
中国华艺广播公司,https://lhttp-hw.qtfm.cn/live/20500139/64k.mp3
漳州人民广播电台交通广播,https://lhttp-hw.qtfm.cn/live/1743/64k.mp3
安溪人民广播电台,https://lhttp-hw.qtfm.cn/live/5022135/64k.mp3
永安广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/15318388/64k.mp3
漳浦广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022658/64k.mp3
尤溪1066,https://lhttp-hw.qtfm.cn/live/5022498/64k.mp3
云霄人民广播电台,https://lhttp-hw.qtfm.cn/live/20500106/64k.mp3
诏安广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500186/64k.mp3
闽侯广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500236/64k.mp3
南平广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022065/64k.mp3
广东,#genre#
广东珠江经济电台,https://lhttp-hw.qtfm.cn/live/1259/64k.mp3
投资传媒（股市广播）,https://lhttp-hw.qtfm.cn/live/4847/64k.mp3
广东城市之声,https://lhttp-hw.qtfm.cn/live/469/64k.mp3
深圳先锋898,https://lhttp-hw.qtfm.cn/live/1270/64k.mp3
广东交通之声,https://lhttp-hw.qtfm.cn/live/1262/64k.mp3
鹤山电台,https://lhttp-hw.qtfm.cn/live/1286/64k.mp3
广州新闻电台,https://lhttp-hw.qtfm.cn/live/4848/64k.mp3
广东音乐之声,https://lhttp-hw.qtfm.cn/live/1260/64k.mp3
广东新闻广播,https://lhttp-hw.qtfm.cn/live/1254/64k.mp3
广州交通广播,https://lhttp-hw.qtfm.cn/live/4955/64k.mp3
中山电台快乐888,https://lhttp-hw.qtfm.cn/live/1278/64k.mp3
广东南方生活广播,https://lhttp-hw.qtfm.cn/live/468/64k.mp3
广东广播电视台文体广播,https://lhttp-hw.qtfm.cn/live/471/64k.mp3
深圳交通频率,https://lhttp-hw.qtfm.cn/live/1272/64k.mp3
珠海斗门电台,https://lhttp-hw.qtfm.cn/live/15318432/64k.mp3
深圳飞扬971,https://lhttp-hw.qtfm.cn/live/1271/64k.mp3
云浮电台综合广播,https://lhttp-hw.qtfm.cn/live/5022442/64k.mp3
广州GZFM88.0,https://lhttp-hw.qtfm.cn/live/20194/64k.mp3
潮州戏曲广播,https://lhttp-hw.qtfm.cn/live/4595/64k.mp3
FM904台山人民广播电台,https://lhttp-hw.qtfm.cn/live/5022062/64k.mp3
花都广播电台,https://lhttp-hw.qtfm.cn/live/1263/64k.mp3
新会人民广播电台,https://lhttp-hw.qtfm.cn/live/5061/64k.mp3
番禺电台畅快1017,https://lhttp-hw.qtfm.cn/live/20212427/64k.mp3
江门旅游之声,https://lhttp-hw.qtfm.cn/live/1283/64k.mp3
广东广播电视台珠江之声,https://lhttp-hw.qtfm.cn/live/470/64k.mp3
中山电台新锐967,https://lhttp-hw.qtfm.cn/live/1277/64k.mp3
江门人民广播电台综合广播,https://lhttp-hw.qtfm.cn/live/1282/64k.mp3
开平广播电台,https://lhttp-hw.qtfm.cn/live/5037/64k.mp3
广州汽车音乐电台,https://lhttp-hw.qtfm.cn/live/20192/64k.mp3
惠州音乐广播,https://lhttp-hw.qtfm.cn/live/5021523/64k.mp3
FM88.7 清远综合广播,https://lhttp-hw.qtfm.cn/live/15318668/64k.mp3
FM95.9清远交通音乐广播,https://lhttp-hw.qtfm.cn/live/20500067/64k.mp3
增城电台FM89.0,https://lhttp-hw.qtfm.cn/live/20211702/64k.mp3
阳江综合资讯广播,https://lhttp-hw.qtfm.cn/live/15318429/64k.mp3
普宁人民广播电台,https://lhttp-hw.qtfm.cn/live/5022527/64k.mp3
茂名综合广播,https://lhttp-hw.qtfm.cn/live/20500088/64k.mp3
潮州交通音乐广播,https://lhttp-hw.qtfm.cn/live/4594/64k.mp3
新兴电台,https://lhttp-hw.qtfm.cn/live/20211602/64k.mp3
澄海人民广播电台,https://lhttp-hw.qtfm.cn/live/5022439/64k.mp3
英德电台,https://lhttp-hw.qtfm.cn/live/5022392/64k.mp3
深圳生活广播,https://lhttp-hw.qtfm.cn/live/1273/64k.mp3
湛江广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20617/64k.mp3
潮州综合频率,https://lhttp-hw.qtfm.cn/live/4596/64k.mp3
FM93.5 茂名交通广播,https://lhttp-hw.qtfm.cn/live/20211574/64k.mp3
韶关综合广播,https://lhttp-hw.qtfm.cn/live/5022074/64k.mp3
龙岗广播FM99.1,https://lhttp-hw.qtfm.cn/live/20160/64k.mp3
梅州广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/1257/64k.mp3
恩平FM97.7,https://lhttp-hw.qtfm.cn/live/20701/64k.mp3
珠海电台交通875,https://lhttp-hw.qtfm.cn/live/1275/64k.mp3
从化广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/15318698/64k.mp3
客都之声 FM103.9,https://lhttp-hw.qtfm.cn/live/5021942/64k.mp3
惠州综合广播FM100,https://lhttp-hw.qtfm.cn/live/5016/64k.mp3
珠海电台先锋951,https://lhttp-hw.qtfm.cn/live/1274/64k.mp3
吴川人民广播电台,https://lhttp-hw.qtfm.cn/live/20211643/64k.mp3
佛冈电台,https://lhttp-hw.qtfm.cn/live/15318379/64k.mp3
化州人民广播电台,https://lhttp-hw.qtfm.cn/live/15318689/64k.mp3
梅州电台交通广播,https://lhttp-hw.qtfm.cn/live/1258/64k.mp3
肇庆高新区广播,https://lhttp-hw.qtfm.cn/live/20500213/64k.mp3
廉江人民广播电台,https://lhttp-hw.qtfm.cn/live/20211578/64k.mp3
遂溪人民广播电台,https://lhttp-hw.qtfm.cn/live/1284/64k.mp3
兴宁市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500218/64k.mp3
东源广播电台,https://lhttp-hw.qtfm.cn/live/20500124/64k.mp3
广西,#genre#
FM950广西音乐台,https://lhttp-hw.qtfm.cn/live/4875/64k.mp3
广西电台新闻910,https://lhttp-hw.qtfm.cn/live/1753/64k.mp3
广西私家车930,https://lhttp-hw.qtfm.cn/live/1756/64k.mp3
广西970女主播电台,https://lhttp-hw.qtfm.cn/live/1754/64k.mp3
广西交通台,https://lhttp-hw.qtfm.cn/live/1758/64k.mp3
南宁1074交通台,https://lhttp-hw.qtfm.cn/live/20767/64k.mp3
南宁990新闻台,https://lhttp-hw.qtfm.cn/live/20358/64k.mp3
978玉林城市电台,https://lhttp-hw.qtfm.cn/live/1762/64k.mp3
贵港金曲1019,https://lhttp-hw.qtfm.cn/live/20697/64k.mp3
桂林飞扬调频,https://lhttp-hw.qtfm.cn/live/1760/64k.mp3
北海新闻综合广播,https://lhttp-hw.qtfm.cn/live/20861/64k.mp3
FM99.10柳州交通广播,https://lhttp-hw.qtfm.cn/live/20571/64k.mp3
广西北部湾之声,https://lhttp-hw.qtfm.cn/live/1757/64k.mp3
北海交通音乐广播,https://lhttp-hw.qtfm.cn/live/20211621/64k.mp3
桂林新闻综合广播,https://lhttp-hw.qtfm.cn/live/1759/64k.mp3
柳州综合广播,https://lhttp-hw.qtfm.cn/live/21043/64k.mp3
畅听882（贺州广播电视台综合广播）,https://lhttp-hw.qtfm.cn/live/5043/64k.mp3
钦州新闻综合广播,https://lhttp-hw.qtfm.cn/live/5042/64k.mp3
云南,#genre#
FM954汽车音乐广播,https://lhttp-hw.qtfm.cn/live/1936/64k.mp3
云南交通之声,https://lhttp-hw.qtfm.cn/live/1928/64k.mp3
云南新闻广播,https://lhttp-hw.qtfm.cn/live/1926/64k.mp3
FM1008新闻综合广播,https://lhttp-hw.qtfm.cn/live/1934/64k.mp3
FM105城市资讯,https://lhttp-hw.qtfm.cn/live/1937/64k.mp3
云南音乐广播,https://lhttp-hw.qtfm.cn/live/1929/64k.mp3
德宏民语综合广播,https://lhttp-hw.qtfm.cn/live/5021850/64k.mp3
昭通新闻综合广播,https://lhttp-hw.qtfm.cn/live/21249/64k.mp3
红河交通广播 ,https://lhttp-hw.qtfm.cn/live/4994/64k.mp3
玉溪新闻综合广播FM102.4,https://lhttp-hw.qtfm.cn/live/5022031/64k.mp3
楚雄综合广播,https://lhttp-hw.qtfm.cn/live/4030/64k.mp3
云南私家车电台,https://lhttp-hw.qtfm.cn/live/1927/64k.mp3
保山广播电视台FM98.7综合广播,https://lhttp-hw.qtfm.cn/live/5022446/64k.mp3
大理电台苍洱调频,https://lhttp-hw.qtfm.cn/live/1940/64k.mp3
镇雄新闻综合广播,https://lhttp-hw.qtfm.cn/live/20210752/64k.mp3
红河综合广播,https://lhttp-hw.qtfm.cn/live/4033/64k.mp3
西双版纳民族语广播FM90.6,https://lhttp-hw.qtfm.cn/live/4036/64k.mp3
昭通交通旅游广播,https://lhttp-hw.qtfm.cn/live/21247/64k.mp3
普洱市广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/1938/64k.mp3
西双版纳综合广播FM101.4,https://lhttp-hw.qtfm.cn/live/5021709/64k.mp3
玉溪交通旅游广播FM87.7,https://lhttp-hw.qtfm.cn/live/20211563/64k.mp3
大理综合广播,https://lhttp-hw.qtfm.cn/live/20207747/64k.mp3
云南民族广播,https://lhttp-hw.qtfm.cn/live/1933/64k.mp3
德宏广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5021849/64k.mp3
文山交通广播,https://lhttp-hw.qtfm.cn/live/5021637/64k.mp3
开远广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022383/64k.mp3
蒙自广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5021599/64k.mp3
弥勒广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/5022531/64k.mp3
巧家人民广播电台——白鹤之声,https://lhttp-hw.qtfm.cn/live/20211704/64k.mp3
普洱市广播电视台交通广播,https://lhttp-hw.qtfm.cn/live/20212429/64k.mp3
怒江广播电视台广播综合频率,https://lhttp-hw.qtfm.cn/live/15318176/64k.mp3
德宏交通旅游广播,https://lhttp-hw.qtfm.cn/live/5022548/64k.mp3
贵州,#genre#
贵州交通广播,https://lhttp-hw.qtfm.cn/live/20057/64k.mp3
贵州广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20063/64k.mp3
贵州FM91.6音乐广播,https://lhttp-hw.qtfm.cn/live/20067/64k.mp3
贵阳综合广播,https://lhttp-hw.qtfm.cn/live/1773/64k.mp3
遵义综合广播,https://lhttp-hw.qtfm.cn/live/20741/64k.mp3
凯里人民广播电台,https://lhttp-hw.qtfm.cn/live/5022045/64k.mp3
安顺综合广播FM105.9,https://lhttp-hw.qtfm.cn/live/5022203/64k.mp3
黔西南FM88.3交通旅游广播,https://lhttp-hw.qtfm.cn/live/5046/64k.mp3
六盘水广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20211616/64k.mp3
黔东南综合广播FM89.8,https://lhttp-hw.qtfm.cn/live/5022285/64k.mp3
七星关综合广播,https://lhttp-hw.qtfm.cn/live/5021866/64k.mp3
织金人民广播电台综合广播,https://lhttp-hw.qtfm.cn/live/20500037/64k.mp3
贵州经济广播,https://lhttp-hw.qtfm.cn/live/20065/64k.mp3
黔西南FM107.9综合广播,https://lhttp-hw.qtfm.cn/live/5045/64k.mp3
毕节交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022712/64k.mp3
威宁阳光945,https://lhttp-hw.qtfm.cn/live/5022342/64k.mp3
兴义之声,https://lhttp-hw.qtfm.cn/live/20500110/64k.mp3
铜仁新闻综合广播,https://lhttp-hw.qtfm.cn/live/20211615/64k.mp3
习水新闻综合广播FM908,https://lhttp-hw.qtfm.cn/live/15318201/64k.mp3
桐梓人民广播电台—娄山之声,https://lhttp-hw.qtfm.cn/live/20212410/64k.mp3
兴仁人民广播电台,https://lhttp-hw.qtfm.cn/live/20500077/64k.mp3
四川,#genre#
四川新闻广播FM106.1,https://lhttp-hw.qtfm.cn/live/4906/64k.mp3
四川交通广播FM101.7,https://lhttp-hw.qtfm.cn/live/4886/64k.mp3
成都年代音乐怀旧好声音,https://lhttp-hw.qtfm.cn/live/20211686/64k.mp3
年代音乐1022,https://lhttp-hw.qtfm.cn/live/20500066/64k.mp3
四川财富生活广播FM94.0,https://lhttp-hw.qtfm.cn/live/4927/64k.mp3
德阳综合广播,https://lhttp-hw.qtfm.cn/live/4987/64k.mp3
成都经济广播,https://lhttp-hw.qtfm.cn/live/1121/64k.mp3
成都电台FM946,https://lhttp-hw.qtfm.cn/live/4892/64k.mp3
欧美音乐88.7,https://lhttp-hw.qtfm.cn/live/15318703/64k.mp3
四川城市之音,https://lhttp-hw.qtfm.cn/live/1111/64k.mp3
成都交通文艺广播FM91.4,https://lhttp-hw.qtfm.cn/live/4891/64k.mp3
四川岷江音乐广播,https://lhttp-hw.qtfm.cn/live/1110/64k.mp3
成都新闻广播,https://lhttp-hw.qtfm.cn/live/4897/64k.mp3
亚洲音乐成都FM96.5,https://lhttp-hw.qtfm.cn/live/4581/64k.mp3
绵阳交通广播,https://lhttp-hw.qtfm.cn/live/4026/64k.mp3
凉山综合广播,https://lhttp-hw.qtfm.cn/live/5022143/64k.mp3
眉山交通音乐广播,https://lhttp-hw.qtfm.cn/live/20207781/64k.mp3
德阳经济生活广播,https://lhttp-hw.qtfm.cn/live/5022110/64k.mp3
泸州新闻广播,https://lhttp-hw.qtfm.cn/live/5021557/64k.mp3
达州综合广播,https://lhttp-hw.qtfm.cn/live/5022394/64k.mp3
南充综合广播FM100.4,https://lhttp-hw.qtfm.cn/live/21357/64k.mp3
四川之声981,https://lhttp-hw.qtfm.cn/live/20207767/64k.mp3
年代音乐FM88.9,https://lhttp-hw.qtfm.cn/live/20500160/64k.mp3
泸州交通广播,https://lhttp-hw.qtfm.cn/live/5021559/64k.mp3
内江交通广播,https://lhttp-hw.qtfm.cn/live/5021907/64k.mp3
攀枝花综合广播,https://lhttp-hw.qtfm.cn/live/4904/64k.mp3
巴中新闻综合广播,https://lhttp-hw.qtfm.cn/live/20210239/64k.mp3
广元交通旅游广播,https://lhttp-hw.qtfm.cn/live/5022581/64k.mp3
自贡综合广播,https://lhttp-hw.qtfm.cn/live/20207784/64k.mp3
绵阳新闻广播,https://lhttp-hw.qtfm.cn/live/4024/64k.mp3
南充交通音乐广播FM91.5,https://lhttp-hw.qtfm.cn/live/21231/64k.mp3
乐山综合广播FM102.8,https://lhttp-hw.qtfm.cn/live/1122/64k.mp3
怀旧金曲广播,https://lhttp-hw.qtfm.cn/live/20207773/64k.mp3
攀枝花交通音乐广播,https://lhttp-hw.qtfm.cn/live/4905/64k.mp3
富顺人民广播电台,https://lhttp-hw.qtfm.cn/live/5022355/64k.mp3
乐山音乐交通广播FM100.5,https://lhttp-hw.qtfm.cn/live/4864/64k.mp3
成都FM96.5,https://lhttp-hw.qtfm.cn/live/20500159/64k.mp3
阆中人民广播电台,https://lhttp-hw.qtfm.cn/live/20500020/64k.mp3
绵竹人民广播电台,https://lhttp-hw.qtfm.cn/live/15318098/64k.mp3
泸州音乐广播,https://lhttp-hw.qtfm.cn/live/5021565/64k.mp3
双流FM1009空港之声,https://lhttp-hw.qtfm.cn/live/20211587/64k.mp3
四川南部新闻综合广播,https://lhttp-hw.qtfm.cn/live/20525/64k.mp3
广元综合广播,https://lhttp-hw.qtfm.cn/live/5022580/64k.mp3
三台人民广播电台,https://lhttp-hw.qtfm.cn/live/15318544/64k.mp3
汽车音乐广播FM942,https://lhttp-hw.qtfm.cn/live/20500137/64k.mp3
FM882 成都故事广播,https://lhttp-hw.qtfm.cn/live/5022004/64k.mp3
自贡文化旅游广播,https://lhttp-hw.qtfm.cn/live/20529/64k.mp3
绵阳音乐广播,https://lhttp-hw.qtfm.cn/live/4025/64k.mp3
德阳旌阳电台,https://lhttp-hw.qtfm.cn/live/5021933/64k.mp3
达州交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022395/64k.mp3
江油人民广播电台,https://lhttp-hw.qtfm.cn/live/20673/64k.mp3
成都龙泉人民广播电台FM93.3,https://lhttp-hw.qtfm.cn/live/20207769/64k.mp3
巴中交通旅游广播,https://lhttp-hw.qtfm.cn/live/20209340/64k.mp3
南部交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022604/64k.mp3
南江人民广播电台,https://lhttp-hw.qtfm.cn/live/20207778/64k.mp3
遂宁新闻综合台,https://lhttp-hw.qtfm.cn/live/20182/64k.mp3
四川民族频率,https://lhttp-hw.qtfm.cn/live/1115/64k.mp3
威远综合广播,https://lhttp-hw.qtfm.cn/live/20500102/64k.mp3
西昌人民广播电台,https://lhttp-hw.qtfm.cn/live/20211706/64k.mp3
苍溪人民广播电台,https://lhttp-hw.qtfm.cn/live/20500228/64k.mp3
FM97.4广汉市广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20212405/64k.mp3
阿坝州综合广播,https://lhttp-hw.qtfm.cn/live/20500234/64k.mp3
中江综合广播994,https://lhttp-hw.qtfm.cn/live/20500148/64k.mp3
新声905,https://lhttp-hw.qtfm.cn/live/20500221/64k.mp3
眉山综合广播,https://lhttp-hw.qtfm.cn/live/4027/64k.mp3
安岳人民广播电台"柠都之声"FM98.0,https://lhttp-hw.qtfm.cn/live/5022417/64k.mp3
仁寿人民广播电台,https://lhttp-hw.qtfm.cn/live/5021453/64k.mp3
广安交通旅游广播,https://lhttp-hw.qtfm.cn/live/21309/64k.mp3
遂宁交通旅游台,https://lhttp-hw.qtfm.cn/live/20180/64k.mp3
蓬安综合广播,https://lhttp-hw.qtfm.cn/live/20500206/64k.mp3
新疆,#genre#
新疆交通广播,https://lhttp-hw.qtfm.cn/live/1910/64k.mp3
新疆电台维语交通文艺广播,https://lhttp-hw.qtfm.cn/live/20639/64k.mp3
新疆新闻广播FM96.1,https://lhttp-hw.qtfm.cn/live/1902/64k.mp3
伊犁维吾尔语综合广播,https://lhttp-hw.qtfm.cn/live/5022688/64k.mp3
乌鲁木齐维吾尔语广播,https://lhttp-hw.qtfm.cn/live/1923/64k.mp3
兵团882综合广播,https://lhttp-hw.qtfm.cn/live/5022410/64k.mp3
新疆929文化旅游广播,https://lhttp-hw.qtfm.cn/live/1909/64k.mp3
乌鲁木齐新闻广播,https://lhttp-hw.qtfm.cn/live/1918/64k.mp3
乌鲁木齐974交通广播,https://lhttp-hw.qtfm.cn/live/1919/64k.mp3
伊犁哈萨克语综合广播,https://lhttp-hw.qtfm.cn/live/5022692/64k.mp3
新疆昌吉 FM103.3综合广播,https://lhttp-hw.qtfm.cn/live/20440/64k.mp3
新疆哈萨克语广播,https://lhttp-hw.qtfm.cn/live/1908/64k.mp3
巴音郭楞广播电视台1077交通文艺广播,https://lhttp-hw.qtfm.cn/live/5022104/64k.mp3
伊犁FM99.5察布查尔,https://lhttp-hw.qtfm.cn/live/5022610/64k.mp3
阿克苏维语综合广播FM101.6,https://lhttp-hw.qtfm.cn/live/15318551/64k.mp3
第二师融媒体中心综合广播FM88.5,https://lhttp-hw.qtfm.cn/live/20211703/64k.mp3
乌鲁木齐旅游音乐,https://lhttp-hw.qtfm.cn/live/1920/64k.mp3
石河子广播电视台综合广播,https://lhttp-hw.qtfm.cn/live/20500118/64k.mp3
伊犁汉语综合广播,https://lhttp-hw.qtfm.cn/live/20211711/64k.mp3
伊犁之声FM89.7,https://lhttp-hw.qtfm.cn/live/20500054/64k.mp3
新疆蒙古语广播,https://lhttp-hw.qtfm.cn/live/1903/64k.mp3
阿克苏市1029,https://lhttp-hw.qtfm.cn/live/20500041/64k.mp3
新疆990音乐广播,https://lhttp-hw.qtfm.cn/live/21001/64k.mp3
巴音郭楞广播电视台FM966综合广播,https://lhttp-hw.qtfm.cn/live/5022108/64k.mp3
库尔勒1053梨城之声,https://lhttp-hw.qtfm.cn/live/20212425/64k.mp3
伊犁交通音乐广播,https://lhttp-hw.qtfm.cn/live/5022689/64k.mp3
奎屯市融媒体中心综合广播,https://lhttp-hw.qtfm.cn/live/20500121/64k.mp3
阿克苏汉语综合广播FM94,https://lhttp-hw.qtfm.cn/live/15318550/64k.mp3
FM100.6 双河综合广播,https://lhttp-hw.qtfm.cn/live/20207772/64k.mp3
托峰明珠交通音乐,https://lhttp-hw.qtfm.cn/live/20207780/64k.mp3
FM96.0 阿拉尔人民广播电台新闻综合广播,https://lhttp-hw.qtfm.cn/live/20500209/64k.mp3
兵团七师综合广播,https://lhttp-hw.qtfm.cn/live/20500095/64k.mp3
塔城人民广播电台汉语综合广播,https://lhttp-hw.qtfm.cn/live/20500031/64k.mp3
FM94.3综合广播,https://lhttp-hw.qtfm.cn/live/20500064/64k.mp3
轮台之声,https://lhttp-hw.qtfm.cn/live/20500099/64k.mp3
塔城市广播电视台FM104.2,https://lhttp-hw.qtfm.cn/live/20500145/64k.mp3
新疆兵团第十三师调频广播,https://lhttp-hw.qtfm.cn/live/5022506/64k.mp3
呼图壁人民广播电台,https://lhttp-hw.qtfm.cn/live/20500188/64k.mp3
西藏,#genre#
拉萨人民广播电台914,https://lhttp-hw.qtfm.cn/live/5022138/64k.mp3
海南,#genre#
交通954,https://lhttp-hw.qtfm.cn/live/5022079/64k.mp3
海南民生广播,https://lhttp-hw.qtfm.cn/live/21243/64k.mp3
海南新闻广播,https://lhttp-hw.qtfm.cn/live/1861/64k.mp3
三亚天涯之声,https://lhttp-hw.qtfm.cn/live/20450/64k.mp3
三亚之声,https://lhttp-hw.qtfm.cn/live/15318203/64k.mp3
海南交通广播,https://lhttp-hw.qtfm.cn/live/4911/64k.mp3
海口音乐广播,https://lhttp-hw.qtfm.cn/live/20010/64k.mp3
海南音乐广播,https://lhttp-hw.qtfm.cn/live/4878/64k.mp3
FM101.8海口综合广播,https://lhttp-hw.qtfm.cn/live/5022015/64k.mp3
琼海人民广播电台,https://lhttp-hw.qtfm.cn/live/5022287/64k.mp3
海南旅游广播•国际旅游岛之声,https://lhttp-hw.qtfm.cn/live/1862/64k.mp3
Live Radio海口生活广播,https://lhttp-hw.qtfm.cn/live/20500233/64k.mp3
万宁综合广播,https://lhttp-hw.qtfm.cn/live/20500237/64k.mp3
网络,#genre#
两广之声音乐台,https://lhttp-hw.qtfm.cn/live/20500149/64k.mp3
怀集音乐之声,https://lhttp-hw.qtfm.cn/live/4804/64k.mp3
清晨音乐台,https://lhttp-hw.qtfm.cn/live/4915/64k.mp3
国际新闻,https://lhttp-hw.qtfm.cn/live/20500172/64k.mp3
AsiaFM 亚洲粤语台,https://lhttp-hw.qtfm.cn/live/15318569/64k.mp3
顺德音乐之声,https://lhttp-hw.qtfm.cn/live/20500150/64k.mp3
动听音乐台,https://lhttp-hw.qtfm.cn/live/5022107/64k.mp3
AsiaFM HD音乐台,https://lhttp-hw.qtfm.cn/live/15318341/64k.mp3
星河音乐,https://lhttp-hw.qtfm.cn/live/20210755/64k.mp3
AsiaFM 亚洲经典台,https://lhttp-hw.qtfm.cn/live/5021912/64k.mp3
海上财经,https://lhttp-hw.qtfm.cn/live/20500170/64k.mp3
AsiaFM 亚洲天空台,https://lhttp-hw.qtfm.cn/live/20071/64k.mp3
新闻听天下,https://lhttp-hw.qtfm.cn/live/20500169/64k.mp3
云梦音乐台,https://lhttp-hw.qtfm.cn/live/20500187/64k.mp3
AsiaFM 亚洲音乐台,https://lhttp-hw.qtfm.cn/live/5022405/64k.mp3
AsiaFM 亚洲热歌台,https://lhttp-hw.qtfm.cn/live/20500208/64k.mp3
郁南音乐台,https://lhttp-hw.qtfm.cn/live/20026/64k.mp3
体坛速听,https://lhttp-hw.qtfm.cn/live/20500171/64k.mp3
CityFM城市音乐台,https://lhttp-hw.qtfm.cn/live/20500153/64k.mp3
湾区音乐台,https://lhttp-hw.qtfm.cn/live/20500163/64k.mp3
891线上音乐台,https://lhttp-hw.qtfm.cn/live/20500215/64k.mp3
西江之声,https://lhttp-hw.qtfm.cn/live/5022379/64k.mp3
中国校园之声,https://lhttp-hw.qtfm.cn/live/20091/64k.mp3
Radio Impetus 心动电台,https://lhttp-hw.qtfm.cn/live/20500161/64k.mp3
阿基米德故事会,https://lhttp-hw.qtfm.cn/live/20500182/64k.mp3
听·越剧,https://lhttp-hw.qtfm.cn/live/20500178/64k.mp3
古典音乐厅,https://lhttp-hw.qtfm.cn/live/20500181/64k.mp3
中国交通网络应急广播,https://lhttp-hw.qtfm.cn/live/20212320/64k.mp3
听梦想FM,https://lhttp-hw.qtfm.cn/live/4917/64k.mp3
乐享音乐,https://lhttp-hw.qtfm.cn/live/4913/64k.mp3
卷卷猫电台,https://lhttp-hw.qtfm.cn/live/20500038/64k.mp3
科技情报站,https://lhttp-hw.qtfm.cn/live/20500175/64k.mp3
Tiktok网络电台,https://lhttp-hw.qtfm.cn/live/5062/64k.mp3
声音控电台,https://lhttp-hw.qtfm.cn/live/15318519/64k.mp3
520电台-520星恋情感电台,https://lhttp-hw.qtfm.cn/live/15318191/64k.mp3
萤火虫网络电台,https://lhttp-hw.qtfm.cn/live/4998/64k.mp3
健康电台,https://lhttp-hw.qtfm.cn/live/20500232/64k.mp3
麻辣966,https://lhttp-hw.qtfm.cn/live/20212393/64k.mp3
上海天气台,https://lhttp-hw.qtfm.cn/live/20500176/64k.mp3
鱼佬音乐坊,https://lhttp-hw.qtfm.cn/live/20500158/64k.mp3
海浪电台,https://lhttp-hw.qtfm.cn/live/20500180/64k.mp3
自强之声,https://lhttp-hw.qtfm.cn/live/5021905/64k.mp3
晋小爱公益之声,https://lhttp-hw.qtfm.cn/live/20500021/64k.mp3
自强健康,https://lhttp-hw.qtfm.cn/live/5022491/64k.mp3
芒果5G（原和鸣）,https://lhttp-hw.qtfm.cn/live/20211693/64k.mp3
"""

    def __init__(self):
        # 解析数据
        self.categories = {}  # 原始分类（省份）
        self.all_stations = []  # 全部电台
        self._parse_data()
        
        # 构建分组
        self.groups = []  # 最终分类列表（顺序：总列表、省份、内容）
        self._build_groups()
        
        # 用于存储每个分类ID对应的频道列表
        self.group_channels = {}
        self._prepare_group_channels()

    def _parse_data(self):
        """解析RADIO_DATA，填充self.categories和self.all_stations"""
        raw = self.RADIO_DATA
        current_cat = None
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.endswith(',#genre#'):
                current_cat = line.replace(',#genre#', '')
                self.categories[current_cat] = []
            elif ',' in line and current_cat:
                name, url = line.split(',', 1)
                if url.startswith('http'):
                    station = {'name': name, 'url': url}
                    self.categories[current_cat].append(station)
                    self.all_stations.append(station)

    def _classify_by_content(self, stations):
        """按内容分类：音乐、新闻经济、其他"""
        music_kw = ['音乐', '文艺', '经典', '流行', '怀旧', '金曲', '年代', '动感', '飞扬', '私家车', '汽车', 'Melody', 'Music']
        news_kw = ['新闻', '综合', '经济', '财经', '资讯', '之声', '故事', '生活', '交通', '旅游', '健康', '教育', '戏曲', '小说', '娱乐', '体育']
        music, news, other = [], [], []
        for s in stations:
            name = s['name']
            if any(kw in name for kw in music_kw):
                music.append(s)
            elif any(kw in name for kw in news_kw):
                news.append(s)
            else:
                other.append(s)
        return {
            '🎵 音乐频道': music,
            '📰 新闻/经济': news,
            '📻 其他频道': other
        }

    def _build_groups(self):
        """构建分组顺序：总列表 -> 省份 -> 内容"""
        # 1. 总列表（不分类）
        self.groups.append({
            'type_id': 'total',
            'type_name': '📡 总列表（不分类）',
            'stations': self.all_stations
        })
        
        # 2. 省份分类（排除"网络"）
        for cat_name, stations in self.categories.items():
            if cat_name == '网络':
                continue
            self.groups.append({
                'type_id': 'prov_' + cat_name,
                'type_name': '📍 ' + cat_name,
                'stations': stations
            })
        
        # 3. 内容分类
        content_dict = self._classify_by_content(self.all_stations)
        for content_name, stations in content_dict.items():
            if stations:
                self.groups.append({
                    'type_id': 'cont_' + content_name,
                    'type_name': content_name,
                    'stations': stations
                })

    def _prepare_group_channels(self):
        """为每个分组建立频道列表映射"""
        for group in self.groups:
            tid = group['type_id']
            stations = group['stations']
            # 转换为vod列表
            vod_list = []
            for s in stations:
                vod_list.append({
                    'vod_id': s['url'],  # 用url作为唯一标识
                    'vod_name': s['name'],
                    'vod_pic': '',
                    'vod_remarks': '直播',
                })
            self.group_channels[tid] = vod_list

    # ---------- TVBox Spider 接口 ----------
    def init(self, extend=""):
        pass

    def getName(self):
        return "全国广播电台"

    def homeContent(self, filter=False):
        """返回分类列表"""
        classes = []
        for group in self.groups:
            classes.append({
                'type_id': group['type_id'],
                'type_name': group['type_name']
            })
        result = {'class': classes}
        if filter:
            result['filters'] = {}
        return result

    def homeVideoContent(self):
        """首页推荐（返回第一个分类）"""
        return self.categoryContent('total', '1', False, {})

    def categoryContent(self, tid, pg='1', filter=False, extend=None):
        """根据分类ID返回频道列表"""
        if tid in self.group_channels:
            vod_list = self.group_channels[tid]
            return {
                'page': 1,
                'pagecount': 1,
                'limit': len(vod_list),
                'total': len(vod_list),
                'list': vod_list
            }
        return {'page': 1, 'pagecount': 1, 'limit': 0, 'total': 0, 'list': []}

    def detailContent(self, ids):
        """获取单个频道详情"""
        if not ids:
            return {'list': []}
        url = str(ids[0]).strip()
        # 查找频道名称
        name = url
        for station in self.all_stations:
            if station['url'] == url:
                name = station['name']
                break
        vod = {
            'vod_id': url,
            'vod_name': name,
            'vod_pic': '',
            'type_name': '广播直播',
            'vod_remarks': '直播',
            'vod_play_from': '蜻蜓FM',
            'vod_play_url': f'直播${url}',
            'vod_content': f'{name} 网络广播',
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags=None):
        """返回播放地址"""
        url = str(id).split('$$$')[-1].strip()
        if url.startswith('http'):
            return {
                'parse': 0,
                'url': url,
                'header': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            }
        return {'parse': 0, 'url': '', 'header': {}}

    def searchContent(self, key, quick=False, pg='1'):
        """搜索频道"""
        keyword = str(key or '').strip().lower()
        if not keyword:
            return {'list': []}
        result = []
        for station in self.all_stations:
            if keyword in station['name'].lower():
                result.append({
                    'vod_id': station['url'],
                    'vod_name': station['name'],
                    'vod_pic': '',
                    'vod_remarks': '直播',
                })
        return {'list': result}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass