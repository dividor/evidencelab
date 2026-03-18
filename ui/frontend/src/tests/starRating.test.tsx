import React from 'react';
import { fireEvent, render } from '@testing-library/react';

import StarRating from '../components/ratings/StarRating';

describe('StarRating', () => {
  test('renders 5 stars', () => {
    render(<StarRating score={0} onChange={jest.fn()} />);
    const stars = document.querySelectorAll('.star-rating-star');
    expect(stars).toHaveLength(5);
  });

  test('fills stars according to score', () => {
    render(<StarRating score={3} onChange={jest.fn()} />);
    const filled = document.querySelectorAll('.star-rating-star.filled');
    expect(filled).toHaveLength(3);
  });

  test('no stars filled when score is 0', () => {
    render(<StarRating score={0} onChange={jest.fn()} />);
    const filled = document.querySelectorAll('.star-rating-star.filled');
    expect(filled).toHaveLength(0);
  });

  test('all stars filled when score is 5', () => {
    render(<StarRating score={5} onChange={jest.fn()} />);
    const filled = document.querySelectorAll('.star-rating-star.filled');
    expect(filled).toHaveLength(5);
  });

  test('clicking a star calls onChange with correct score', () => {
    const handleChange = jest.fn();
    render(<StarRating score={0} onChange={handleChange} />);
    const stars = document.querySelectorAll('.star-rating-star');
    // Click the 4th star (index 3, score = 4)
    fireEvent.click(stars[3]);
    expect(handleChange).toHaveBeenCalledWith(4);
  });

  test('clicking first star calls onChange with 1', () => {
    const handleChange = jest.fn();
    render(<StarRating score={0} onChange={handleChange} />);
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[0]);
    expect(handleChange).toHaveBeenCalledWith(1);
  });

  test('clicking fifth star calls onChange with 5', () => {
    const handleChange = jest.fn();
    render(<StarRating score={0} onChange={handleChange} />);
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[4]);
    expect(handleChange).toHaveBeenCalledWith(5);
  });

  test('read-only mode does not call onChange', () => {
    const handleChange = jest.fn();
    render(<StarRating score={3} onChange={handleChange} readOnly />);
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[0]);
    expect(handleChange).not.toHaveBeenCalled();
  });

  test('renders with custom size', () => {
    render(<StarRating score={2} onChange={jest.fn()} size={20} />);
    const stars = document.querySelectorAll('.star-rating-star');
    expect(stars[0]).toHaveStyle({ fontSize: '20px' });
  });

  test('default size is 16px', () => {
    render(<StarRating score={0} onChange={jest.fn()} />);
    const stars = document.querySelectorAll('.star-rating-star');
    expect(stars[0]).toHaveStyle({ fontSize: '16px' });
  });

  test('calls onRequestModal instead of onChange when modal handler is set', () => {
    const handleChange = jest.fn();
    const handleModal = jest.fn();
    render(
      <StarRating score={0} onChange={handleChange} onRequestModal={handleModal} />,
    );
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.click(stars[2]);
    expect(handleModal).toHaveBeenCalledWith(3);
    expect(handleChange).not.toHaveBeenCalled();
  });

  test('keyboard Enter on star triggers click', () => {
    const handleChange = jest.fn();
    render(<StarRating score={0} onChange={handleChange} />);
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.keyDown(stars[1], { key: 'Enter' });
    expect(handleChange).toHaveBeenCalledWith(2);
  });

  test('keyboard Space on star triggers click', () => {
    const handleChange = jest.fn();
    render(<StarRating score={0} onChange={handleChange} />);
    const stars = document.querySelectorAll('.star-rating-star');
    fireEvent.keyDown(stars[3], { key: ' ' });
    expect(handleChange).toHaveBeenCalledWith(4);
  });

  test('applies custom className', () => {
    render(<StarRating score={0} onChange={jest.fn()} className="my-rating" />);
    const container = document.querySelector('.star-rating.my-rating');
    expect(container).toBeTruthy();
  });
});
