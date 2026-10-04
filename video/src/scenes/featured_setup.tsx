import {AbsoluteFill} from 'remotion';
import capture from '../../public/captures/site/featured_run.json';
import {copy, story} from '../content';
import {palette, fonts} from '../theme';
import {ScreenshotPushIn} from '../components/ScreenshotPushIn';
import {LowerThird} from '../components/LowerThird';
import {Reveal} from '../components/Motion';
import {NodeText} from '../components/NodeText';
import type {SceneProps} from './types';

export function FeaturedSetup({speechDuration}: SceneProps) {
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, top: 330}}><ScreenshotPushIn page="featured_run" capture={capture} contains={story.featured.issue_title} focus="issue" width={1360} height={720} duration={speechDuration}/></div>
    <Reveal style={{position: 'absolute', left: 1580, right: 128, top: 245}}>
      <div style={{fontSize: 96, lineHeight: 1.15, fontWeight: 500}}>{copy.featured.spec}</div>
      {story.featured.spec_tests.map((test, i) => <div key={test} style={{marginTop: i === 0 ? 45 : 20, padding: '22px 0', borderTop: `2px solid ${palette.border}`, fontFamily: fonts.mono, fontSize: 48, color: palette.accent, lineHeight: 1.4}}><NodeText text={test} short/></div>)}
    </Reveal>
    <LowerThird title={copy.featured.label.replace('{tasks}', String(story.numbers.tasks))} detail={story.featured.run_id} top={1110} centered size={48}/>
  </AbsoluteFill>;
}
