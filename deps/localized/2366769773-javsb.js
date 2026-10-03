rule = {
    name: 'javsb',
    host: 'https://jav.sb',
    homeVodJS: `
    request(HOST);|||
    const $ = load(html);
    videos = _.map($('div.rounded'), item => {
      return {
        vod_id: $('a', item).attr('href'),
        vod_name: $('img', item).attr('alt'),
        vod_pic: HOST + $('img', item).attr('data-src'),
        vod_remarks: $('span', item).text(),
      }
    });
    `,
    class_name: '最近更新&最新上市&日本有码&日本无码&FC2-PPV&无码破解&中文字幕&MGS动画&写真&国产',
    class_url: '/label/rank&/label/new&/javtype/Censored&/javtype/Uncensored&/javtype/FC2-PPV&/javtype/Mosaic_Removed&/javtype/CHN_SUB&/javtype/MGS&/javtype/Adult_IDOL&/javtype/Asian_Amateur',
    categoryVodJS:`
      let url = HOST + '/'+classId;
      if(classId.startsWith('/javtype')) url = url + '-' + page + '.html';
      if(classId.startsWith('/label')) url = url + '/page/' + page + '.html';
      request(url);|||
      const $ = load(html);
      videos = _.map($('div.rounded'), item => {
        return {
          vod_id: $('a', item).attr('href'),
          vod_name: $('img', item).attr('alt'),
          vod_pic: HOST + $('img', item).attr('data-src'),
          vod_remarks: $('span', item).text(),
        }
      });
    `,
    detailVodJS: `
      request(HOST + input);|||
      const $ = load(html);
      var vod = {
        type_name: $('a.cat').text(),
        vod_year: $('.text-secondary:nth-child(3) .font-medium').text(),
        vod_content: HOST + input,
        vod_play_from: 'leospring',
        vod_play_url: JSON.parse(html.split('player_aaaa=')[1].split('</script>')[0])['url'],
      }
      videos.push(vod);
    `,
  }