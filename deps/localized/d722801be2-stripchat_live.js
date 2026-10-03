rule = {
    host: 'https://zh.stripchat.com',
    class_name: '中文&乌克兰&美国&新主播&VR摄像头&最佳私人秀&调情&虐恋',
    class_url: 'tagLanguageChinese&tagLanguageUkrainian&tagLanguageUSModels&autoTagNew&autoTagVr&autoTagBestPrivates&autoTagNonNude&subcultureBdsm',
    categoryVodJS: `
      let url = 'https://proxy.leospring.eu.org/' + HOST + '/api/front/models/get-list';
      let params = {
        "limit": 36,
        "offset": (page-1)*36,
        "primaryTag": "girls",
        "filterGroupTags": [[classId]]
      };
      request(url, params, {'Content-Type': 'application/json'}, 'POST');|||
      videos = _.map(JSON.parse(html).models, item => {
        return {
          vod_id: item.hlsPlaylist.replace(/_(.*?)p/,'_auto'),
          vod_name: item.username,
          vod_pic: 'https://img.strpst.com/thumbs/'+item.snapshotTimestamp+'/'+item.id+'_webp',
          vod_remarks: item.isLive ? '在线': '下线',
        }
      });
    `,
    detailVodJS: `
      let vod = {
        vod_content: input,
        vod_play_from: 'leospring',
        vod_play_url: 'leospring$'+input,
      };
      videos.push(vod);
    `,
  }