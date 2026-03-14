import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ConfirmModal from '../components/admin/ConfirmModal';

describe('ConfirmModal', () => {
  const defaultProps = {
    title: 'Delete Item',
    message: 'Are you sure you want to delete this?',
    onConfirm: jest.fn(),
    onCancel: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders title and message', () => {
    render(<ConfirmModal {...defaultProps} />);
    expect(screen.getByText('Delete Item')).toBeInTheDocument();
    expect(screen.getByText('Are you sure you want to delete this?')).toBeInTheDocument();
  });

  test('renders default confirm label', () => {
    render(<ConfirmModal {...defaultProps} />);
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  test('renders custom confirm label', () => {
    render(<ConfirmModal {...defaultProps} confirmLabel="Remove User" />);
    expect(screen.getByText('Remove User')).toBeInTheDocument();
  });

  test('calls onConfirm when confirm button clicked', () => {
    render(<ConfirmModal {...defaultProps} />);
    fireEvent.click(screen.getByText('Delete'));
    expect(defaultProps.onConfirm).toHaveBeenCalledTimes(1);
  });

  test('calls onCancel when cancel button clicked', () => {
    render(<ConfirmModal {...defaultProps} />);
    fireEvent.click(screen.getByText('Cancel'));
    expect(defaultProps.onCancel).toHaveBeenCalledTimes(1);
  });

  test('calls onCancel when overlay clicked', () => {
    const { container } = render(<ConfirmModal {...defaultProps} />);
    const overlay = container.querySelector('.confirm-modal-overlay');
    expect(overlay).toBeTruthy();
    fireEvent.click(overlay!);
    expect(defaultProps.onCancel).toHaveBeenCalledTimes(1);
  });

  test('does not call onCancel when modal body clicked', () => {
    const { container } = render(<ConfirmModal {...defaultProps} />);
    const modal = container.querySelector('.confirm-modal');
    expect(modal).toBeTruthy();
    fireEvent.click(modal!);
    expect(defaultProps.onCancel).not.toHaveBeenCalled();
  });
});
