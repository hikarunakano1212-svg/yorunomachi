import pyarrow.fs as fs, pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa, json, sys
from concurrent.futures import ThreadPoolExecutor
s=fs.S3FileSystem(anonymous=True, region='us-west-2')
theme, box, out = sys.argv[1], [float(x) for x in sys.argv[2].split(',')], sys.argv[3]
x0,y0,x1,y1=box
files=[f.path for f in s.get_file_info(fs.FileSelector('overturemaps-us-west-2/release/2026-09-23.1/'+theme))]
def scan(path):
    pf=pq.ParquetFile(path, filesystem=s)
    md=pf.metadata; names=pf.schema_arrow.names
    rows=[]
    # bbox struct 列の統計で行グループを絞る
    idx={md.schema.column(i).path:i for i in range(md.num_columns)}
    for rg in range(md.num_row_groups):
        r=md.row_group(rg)
        st=lambda k: r.column(idx[k]).statistics
        try:
            if st('bbox.xmin').min>x1 or st('bbox.xmax').max<x0 or st('bbox.ymin').min>y1 or st('bbox.ymax').max<y0: continue
        except Exception: pass
        t=pf.read_row_group(rg)
        b=t.column('bbox').combine_chunks()
        m=pc.and_(pc.and_(pc.greater(b.field('xmax'),x0),pc.less(b.field('xmin'),x1)),pc.and_(pc.greater(b.field('ymax'),y0),pc.less(b.field('ymin'),y1)))
        t=t.filter(m)
        if t.num_rows: rows.append(t)
    return rows
res=[]
with ThreadPoolExecutor(32) as ex:
    for i,r in enumerate(ex.map(scan,files)):
        res+=r
print(theme, sum(t.num_rows for t in res))
import shapely
feats=[]
for t in res:
    d=t.to_pylist()
    for row in d:
        g=shapely.from_wkb(row['geometry'])
        o={k:row.get(k) for k in ('height','num_floors','class','subtype','min_height','roof_shape','facade_material','roof_material') if row.get(k) is not None}
        nm=row.get('names'); 
        if nm and nm.get('primary'): o['name']=nm['primary']
        if 'road_flags' in row and row.get('road_flags'): o['flags']=[f['values'] for f in row['road_flags']]
        if row.get('level_rules'): o['level']=[l['value'] for l in row['level_rules']]
        # 一方通行: 進行方向ごとの通行禁止ルール
        for ar in row.get('access_restrictions') or []:
            w=ar.get('when') or {}
            if ar.get('access_type')=='denied' and w.get('heading') and not w.get('mode') and not w.get('during'):
                o['oneway_denied']=w['heading']
        o['g']=shapely.geometry.mapping(g)
        feats.append(o)
json.dump(feats,open(out,'w'))
