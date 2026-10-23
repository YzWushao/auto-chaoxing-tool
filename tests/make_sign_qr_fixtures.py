"""Generate artificial local QR images for manual browser checks; no real tokens."""
import argparse
from pathlib import Path

import qrcode
from PIL import Image


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, activity, token in [('valid', '902', 'OFFLINE_QR_TOKEN_123456789'),
                                  ('different-activity', '999', 'OTHER_ACTIVITY_TOKEN_12345'),
                                  ('expired-rejected', '902', 'EXPIRED_TEST_TOKEN_12345')]:
        content = f'https://mobilelearn.chaoxing.com/widget/sign/e?id={activity}&enc={token}'
        qrcode.make(content).save(args.output / f'{name}.png')
    Image.new('RGB', (320, 240), 'white').save(args.output / 'blank.png')
    print('Artificial test images:', args.output.resolve())
